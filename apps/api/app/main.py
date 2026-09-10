from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis import Redis

from app.activation.routes import router as activation_router
from app.activation.service import ActivationError, ActivationService
from app.admin.routes import router as admin_router
from app.audit.service import AuditLogService
from app.auth.hto import HTOAuthError, HTOService
from app.auth.pin import PINService
from app.auth.routes import router as auth_router
from app.checkins.routes import router as checkin_router
from app.config import Settings, get_settings
from app.container import (
    CeleryEsimIssuanceScheduler,
    CeleryProvisioningScheduler,
    build_notification_service,
    build_otp_service,
    build_payment_providers,
    default_dependencies,
)
from app.db import SessionFactory
from app.esim.providers import EsimProvider, build_esim_providers
from app.esim.routes import router as esim_router
from app.esim.service import (
    DeviceCompatibilityService,
    EsimError,
    EsimIssuanceScheduler,
    EsimProfileService,
    HtoPilgrimService,
    NoopEsimIssuanceScheduler,
)
from app.health import LivenessResponse, ReadinessResponse, check_readiness
from app.i18n import api_message, localize_validation_errors, request_locale
from app.identity.delivery import (
    DeliveryTransport,
    NullDeliveryTransport,
    RecordingDeliveryTransport,
)
from app.identity.service import IdentityError, IdentityService
from app.manifests.invoices import InvoiceStorage, build_invoice_storage
from app.manifests.orders import ManifestOrderService, ProvisioningScheduler
from app.manifests.routes import pricing_router
from app.manifests.routes import router as manifest_router
from app.manifests.service import ManifestError, ManifestService
from app.monitoring import PostHogExceptionMiddleware, build_exception_tracker
from app.notifications.service import EmailSender, WhatsAppSender
from app.otp.providers.base import OTPProvider
from app.otp.routes import router as otp_webhook_router
from app.otp.service import FailoverScheduler, OTPError, RedisClient, utc_now
from app.packages.service import (
    PackageAdminService,
    PackageChainingService,
    PackageError,
)
from app.payments.providers import PaymentProvider
from app.payments.routes import router as payment_router
from app.payments.service import PaymentError, PaymentService
from app.pricing.routes import router as retail_pricing_router
from app.pricing.service import RetailPricingService
from app.profile.device_tokens import DeviceTokenService
from app.profile.routes import router as profile_router
from app.reports.routes import router as reports_router
from app.reports.service import ProvisioningReportService
from app.retention.service import RetentionService
from app.retirement import RetiredFeatureError
from app.sos.routes import router as sos_router
from app.voice.providers import TelnyxVoiceProvider, VoiceProvider
from app.voice.routes import router as voice_router
from app.voice.service import VoiceError, VoiceService


def create_app(
    settings: Settings | None = None,
    redis_client: Redis | None = None,
    providers: Mapping[str, OTPProvider] | None = None,
    scheduler: FailoverScheduler | None = None,
    session_factory: SessionFactory | None = None,
    clock: Callable[[], datetime] = utc_now,
    email_sender: EmailSender | None = None,
    whatsapp_sender: WhatsAppSender | None = None,
    invoice_storage: InvoiceStorage | None = None,
    provisioning_scheduler: ProvisioningScheduler | None = None,
    payment_providers: Mapping[str, PaymentProvider] | None = None,
    voice_provider: VoiceProvider | None = None,
    identity_transport: DeliveryTransport | None = None,
    esim_providers: Mapping[str, EsimProvider] | None = None,
    esim_scheduler: EsimIssuanceScheduler | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    supplied = (redis_client, providers, scheduler, session_factory)
    if any(value is None for value in supplied):
        defaults = default_dependencies(resolved_settings)
        if redis_client is None:
            redis_client = defaults[0]
        if session_factory is None:
            session_factory = defaults[1]
        if scheduler is None:
            scheduler = defaults[2]
        if providers is None:
            providers = defaults[3]

    assert redis_client is not None
    assert session_factory is not None
    assert scheduler is not None
    assert providers is not None

    api = FastAPI(title="DamDam API", version="0.1.0")
    api.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.dashboard_base_url.rstrip("/")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    exception_tracker = build_exception_tracker(resolved_settings)
    if exception_tracker is not None:
        api.add_middleware(
            PostHogExceptionMiddleware,
            tracker=exception_tracker,
            environment=resolved_settings.app_env,
        )
    api.state.settings = resolved_settings
    api.state.clock = clock
    api.state.session_factory = session_factory
    api.state.redis_client = redis_client
    api.state.otp_service = build_otp_service(
        resolved_settings,
        cast(RedisClient, redis_client),
        scheduler,
        providers,
        clock,
    )
    api.state.pin_service = PINService(clock)
    api.state.retention_service = RetentionService(clock)
    notification_service = build_notification_service(
        resolved_settings, email_sender, whatsapp_sender
    )
    resolved_esim_scheduler = esim_scheduler or (
        NoopEsimIssuanceScheduler()
        if resolved_settings.app_env == "test"
        else CeleryEsimIssuanceScheduler()
    )
    api.state.manifest_service = ManifestService()
    api.state.manifest_order_service = ManifestOrderService(
        resolved_settings,
        notification_service,
        invoice_storage or build_invoice_storage(resolved_settings),
        provisioning_scheduler or CeleryProvisioningScheduler(),
        clock,
    )
    api.state.hto_service = HTOService(resolved_settings, notification_service, clock)
    api.state.device_token_service = DeviceTokenService(clock)
    api.state.identity_transport = identity_transport or (
        RecordingDeliveryTransport()
        if resolved_settings.app_env == "test"
        else NullDeliveryTransport()
    )
    api.state.identity_service = IdentityService(
        transport=api.state.identity_transport,
        clock=clock,
        redis=redis_client,
    )
    resolved_chaining_service = PackageChainingService(clock)
    resolved_audit_service = AuditLogService(clock)
    api.state.audit_service = resolved_audit_service
    api.state.package_admin_service = PackageAdminService(resolved_audit_service)
    api.state.activation_service = ActivationService(
        clock,
        resolved_esim_scheduler,
        resolved_chaining_service,
        resolved_audit_service,
    )
    api.state.retail_pricing_service = RetailPricingService()
    api.state.payment_service = PaymentService(
        resolved_settings,
        payment_providers or build_payment_providers(resolved_settings),
        notification_service,
        clock,
        resolved_esim_scheduler,
        resolved_chaining_service,
        resolved_audit_service,
    )
    api.state.device_compatibility_service = DeviceCompatibilityService(clock)
    api.state.esim_profile_service = EsimProfileService(
        resolved_settings,
        esim_providers or build_esim_providers(resolved_settings),
        resolved_esim_scheduler,
        notification_service,
        clock,
    )
    api.state.hto_pilgrim_service = HtoPilgrimService()
    api.state.report_service = ProvisioningReportService(clock)
    api.state.voice_service = VoiceService(
        resolved_settings,
        voice_provider or TelnyxVoiceProvider(resolved_settings),
        clock,
        cast(RedisClient, redis_client),
    )

    @api.exception_handler(IdentityError)
    async def identity_error_handler(
        request: Request, exc: IdentityError
    ) -> JSONResponse:
        statuses = {
            "identity_token_invalid": 400,
            "identity_token_expired": 400,
            "identifier_already_verified": 409,
            "identity_send_throttled": 429,
        }
        headers = {}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
            headers=headers,
        )

    @api.exception_handler(RetiredFeatureError)
    async def retired_feature_handler(
        request: Request, exc: RetiredFeatureError
    ) -> JSONResponse:
        # 410 rather than 404: the feature is gone on purpose, and a client
        # must not read the refusal as a routing fault worth retrying.
        return JSONResponse(
            status_code=410,
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {"feature": exc.feature, "upgrade_required": True},
            },
        )

    @api.exception_handler(EsimError)
    async def esim_error_handler(request: Request, exc: EsimError) -> JSONResponse:
        statuses = {
            "aggregator_unavailable": 502,
            "package_not_found": 404,
            "package_not_active": 409,
            "esim_profile_not_found": 404,
        }
        return JSONResponse(
            status_code=statuses[exc.code],
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(OTPError)
    async def otp_error_handler(request: Request, exc: OTPError) -> JSONResponse:
        statuses = {
            "invalid_otp": 400,
            "otp_expired": 400,
            "rate_limited": 429,
            "locked": 423,
            # Returned only after successful OTP verification, never by the
            # unauthenticated request endpoint.
            "account_not_found": 404,
            "otp_unavailable": 503,
            "invalid_refresh_token": 401,
            "invalid_webhook_signature": 401,
            "invalid_webhook_payload": 400,
            "pin_too_weak": 400,
            "invalid_pin": 400,
            "pin_not_set": 400,
            "invalid_access_token": 401,
        }
        details: dict[str, Any] = {}
        if exc.retry_after is not None:
            details["retry_after"] = exc.retry_after
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": details,
            },
        )

    @api.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = localize_validation_errors(exc.errors(), request_locale(request))
        if any(error["type"] == "pin_too_weak" for error in errors):
            return JSONResponse(
                status_code=400,
                content={
                    "error": "pin_too_weak",
                    "message": api_message(request, "pin_too_weak"),
                    "details": {},
                },
            )
        serializable_errors = []
        for error in errors:
            serialized = dict(error)
            if "ctx" in serialized:
                serialized["ctx"] = {
                    key: str(value) for key, value in serialized["ctx"].items()
                }
            serializable_errors.append(serialized)
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "message": api_message(request, "validation_error"),
                "details": {"errors": serializable_errors},
            },
        )

    @api.exception_handler(HTOAuthError)
    async def hto_error_handler(request: Request, exc: HTOAuthError) -> JSONResponse:
        statuses = {
            "email_already_registered": 409,
            "invalid_verification_token": 400,
            "invalid_credentials": 401,
            "email_not_verified": 403,
            "pending_approval": 403,
            "rejected": 403,
            "invalid_admin_token": 401,
            "operator_not_found": 404,
            "invalid_approval_transition": 409,
            "notification_unavailable": 503,
            "invalid_operator_token": 401,
        }
        return JSONResponse(
            status_code=statuses[exc.code],
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(ManifestError)
    async def manifest_error_handler(
        request: Request, exc: ManifestError
    ) -> JSONResponse:
        statuses = {
            "csv_required": 415,
            "malformed_csv": 400,
            "missing_required_columns": 400,
            "row_limit_exceeded": 400,
            "manifest_not_found": 404,
            "manifest_already_confirmed": 409,
            "no_valid_rows": 400,
            "manifest_not_confirmed": 409,
            "pricing_tier_not_found": 404,
            "pricing_unavailable": 503,
            "invalid_pilgrim_selection": 400,
            "pilgrims_already_grouped": 409,
            "family_group_not_found": 404,
            "invalid_family_group_size": 400,
            "family_group_required": 400,
            "complete_family_group_required": 400,
            "individual_pilgrims_required": 400,
            "pilgrims_already_ordered": 409,
            "manifest_order_not_found": 404,
            "invoice_unavailable": 503,
            "invoice_email_unavailable": 503,
            "invalid_payment_transition": 409,
            "provisioning_unavailable": 503,
            "payment_not_confirmed": 409,
            "activation_code_unavailable": 503,
            "activation_delivery_incomplete": 503,
        }
        return JSONResponse(
            status_code=statuses[exc.code],
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": jsonable_encoder(exc.details),
            },
        )

    @api.exception_handler(ActivationError)
    async def activation_error_handler(
        request: Request, exc: ActivationError
    ) -> JSONResponse:
        statuses = {
            "activation_code_invalid": 404,
            "activation_code_already_used": 409,
            "activation_code_expired": 410,
            "activation_code_phone_mismatch": 403,
        }
        return JSONResponse(
            status_code=statuses[exc.code],
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(PaymentError)
    async def payment_error_handler(
        request: Request, exc: PaymentError
    ) -> JSONResponse:
        statuses = {
            "pricing_tier_not_found": 404,
            "invalid_group_size": 400,
            "payment_unavailable": 503,
            "invalid_processor": 404,
            "invalid_webhook_signature": 401,
            "invalid_webhook_payload": 400,
            "package_not_found": 404,
        }
        return JSONResponse(
            status_code=statuses[exc.code],
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(PackageError)
    async def package_error_handler(
        request: Request, exc: PackageError
    ) -> JSONResponse:
        statuses = {"package_not_found": 404}
        return JSONResponse(
            status_code=statuses[exc.code],
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(VoiceError)
    async def voice_error_handler(request: Request, exc: VoiceError) -> JSONResponse:
        statuses = {
            "invalid_webhook_signature": 401,
            "invalid_webhook_payload": 400,
            "cli_not_verified": 403,
            "pstn_balance_exhausted": 409,
            "voice_unavailable": 503,
        }
        return JSONResponse(
            status_code=statuses[exc.code],
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.get("/health/live", tags=["system"])
    def liveness() -> LivenessResponse:
        return LivenessResponse()

    @api.get(
        "/health",
        tags=["system"],
        response_model=ReadinessResponse,
        responses={503: {"model": ReadinessResponse, "description": "Not Ready"}},
    )
    def health() -> ReadinessResponse | JSONResponse:
        result = check_readiness(
            api.state.session_factory,
            api.state.redis_client,
        )
        if result.status == "not_ready":
            return JSONResponse(status_code=503, content=result.model_dump())
        return result

    api.include_router(auth_router, prefix="/v1")
    api.include_router(admin_router, prefix="/v1")
    api.include_router(manifest_router, prefix="/v1")
    api.include_router(pricing_router, prefix="/v1")
    api.include_router(otp_webhook_router, prefix="/v1")
    api.include_router(profile_router, prefix="/v1")
    api.include_router(activation_router, prefix="/v1")
    api.include_router(retail_pricing_router, prefix="/v1")
    api.include_router(payment_router, prefix="/v1")
    api.include_router(esim_router, prefix="/v1")
    api.include_router(reports_router, prefix="/v1")
    api.include_router(voice_router, prefix="/v1")
    api.include_router(checkin_router, prefix="/v1")
    api.include_router(sos_router, prefix="/v1")
    return api


app = create_app()
