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
from app.auth.hto import HTOAuthError, HTOService
from app.auth.pin import PINService
from app.auth.routes import router as auth_router
from app.config import Settings, get_settings
from app.container import (
    CeleryProvisioningScheduler,
    build_notification_service,
    build_otp_service,
    default_dependencies,
)
from app.db import SessionFactory
from app.manifests.invoices import InvoiceStorage, build_invoice_storage
from app.manifests.orders import ManifestOrderService, ProvisioningScheduler
from app.manifests.routes import pricing_router
from app.manifests.routes import router as manifest_router
from app.manifests.service import ManifestError, ManifestService
from app.notifications.service import EmailSender, WhatsAppSender
from app.otp.providers.base import OTPProvider
from app.otp.routes import router as otp_webhook_router
from app.otp.service import FailoverScheduler, OTPError, RedisClient, utc_now
from app.profile.family_contacts import FamilyContactError, FamilyContactService
from app.profile.routes import router as profile_router


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
    api.state.settings = resolved_settings
    api.state.clock = clock
    api.state.session_factory = session_factory
    api.state.otp_service = build_otp_service(
        resolved_settings,
        cast(RedisClient, redis_client),
        scheduler,
        providers,
        clock,
    )
    api.state.pin_service = PINService(clock)
    notification_service = build_notification_service(
        resolved_settings, email_sender, whatsapp_sender
    )
    api.state.manifest_service = ManifestService()
    api.state.manifest_order_service = ManifestOrderService(
        resolved_settings,
        notification_service,
        invoice_storage or build_invoice_storage(resolved_settings),
        provisioning_scheduler or CeleryProvisioningScheduler(),
        clock,
    )
    api.state.hto_service = HTOService(
        resolved_settings, notification_service, clock
    )
    api.state.family_contact_service = FamilyContactService(
        notification_service, clock
    )
    api.state.activation_service = ActivationService(clock)

    @api.exception_handler(OTPError)
    async def otp_error_handler(request: Request, exc: OTPError) -> JSONResponse:
        del request
        statuses = {
            "invalid_otp": 400,
            "otp_expired": 400,
            "rate_limited": 429,
            "locked": 423,
            "account_exists": 409,
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
        messages = {
            "invalid_otp": "The verification code is incorrect.",
            "otp_expired": "The verification code has expired.",
            "rate_limited": "Please wait before requesting another code.",
            "locked": "Too many attempts. Please wait before trying again.",
            "account_exists": "This number already has an account. Please log in.",
            "account_not_found": "No account exists for this phone number.",
            "otp_unavailable": "Verification is temporarily unavailable.",
            "invalid_refresh_token": "The refresh token is invalid or expired.",
            "invalid_webhook_signature": "Webhook signature is invalid.",
            "invalid_webhook_payload": "Webhook payload is invalid.",
            "pin_too_weak": "Choose a non-repeated, non-sequential 4-digit PIN.",
            "invalid_pin": "The PIN is incorrect.",
            "pin_not_set": "Set a PIN before trying to unlock the app.",
            "invalid_access_token": "The access token is invalid or expired.",
        }
        details: dict[str, Any] = {}
        if exc.retry_after is not None:
            details["retry_after"] = exc.retry_after
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": messages[exc.code],
                "details": details,
            },
        )

    @api.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del request
        errors = exc.errors()
        if any(error["type"] == "pin_too_weak" for error in errors):
            return JSONResponse(
                status_code=400,
                content={
                    "error": "pin_too_weak",
                    "message": (
                        "Choose a non-repeated, non-sequential 4-digit PIN."
                    ),
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
                "message": "The request contains invalid fields.",
                "details": {"errors": serializable_errors},
            },
        )

    @api.exception_handler(HTOAuthError)
    async def hto_error_handler(request: Request, exc: HTOAuthError) -> JSONResponse:
        del request
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
        messages = {
            "email_already_registered": "This email already has an account.",
            "invalid_verification_token": (
                "The verification link is invalid or expired."
            ),
            "invalid_credentials": "The email or password is incorrect.",
            "email_not_verified": "Verify your email before continuing.",
            "pending_approval": "Your account is pending admin approval.",
            "rejected": "Your operator registration was rejected.",
            "invalid_admin_token": "A valid administrator session is required.",
            "operator_not_found": "The operator account was not found.",
            "invalid_approval_transition": (
                "The account cannot be updated from its current approval state."
            ),
            "notification_unavailable": (
                "Notification delivery is temporarily unavailable."
            ),
            "invalid_operator_token": "A valid HTO operator session is required.",
        }
        return JSONResponse(
            status_code=statuses[exc.code],
            content={"error": exc.code, "message": messages[exc.code], "details": {}},
        )

    @api.exception_handler(ManifestError)
    async def manifest_error_handler(
        request: Request, exc: ManifestError
    ) -> JSONResponse:
        del request
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
        messages = {
            "csv_required": "Upload a CSV file.",
            "malformed_csv": "The CSV file could not be parsed.",
            "missing_required_columns": (
                "The CSV must include first_name, last_name, and phone_number."
            ),
            "row_limit_exceeded": "A manifest can contain at most 500 rows.",
            "manifest_not_found": "The manifest was not found.",
            "manifest_already_confirmed": "This manifest has already been confirmed.",
            "no_valid_rows": "The manifest has no valid rows to confirm.",
            "manifest_not_confirmed": "Confirm the manifest before placing orders.",
            "pricing_tier_not_found": "The selected pricing tier is unavailable.",
            "pricing_unavailable": "Current package pricing is unavailable.",
            "invalid_pilgrim_selection": "Select valid pilgrims from this manifest.",
            "pilgrims_already_grouped": (
                "One or more pilgrims already belong to a family group."
            ),
            "family_group_not_found": "The family group was not found.",
            "invalid_family_group_size": (
                "The family group size is outside the tier limits."
            ),
            "family_group_required": "Select one complete Family group for this tier.",
            "complete_family_group_required": (
                "Every member of the Family group must be selected."
            ),
            "individual_pilgrims_required": "Grouped pilgrims require the Family tier.",
            "pilgrims_already_ordered": (
                "One or more pilgrims are already included in an order."
            ),
            "manifest_order_not_found": "The manifest order was not found.",
            "invoice_unavailable": "Invoice generation is temporarily unavailable.",
            "invoice_email_unavailable": (
                "The order was saved, but invoice email delivery is unavailable."
            ),
            "invalid_payment_transition": (
                "This order cannot be confirmed from its current state."
            ),
            "provisioning_unavailable": (
                "Payment was recorded, but provisioning could not be queued."
            ),
            "payment_not_confirmed": "Payment must be confirmed before provisioning.",
            "activation_code_unavailable": "An activation code could not be generated.",
            "activation_delivery_incomplete": (
                "One or more activation links could not be delivered."
            ),
        }
        return JSONResponse(
            status_code=statuses[exc.code],
            content={
                "error": exc.code,
                "message": messages[exc.code],
                "details": jsonable_encoder(exc.details),
            },
        )

    @api.exception_handler(FamilyContactError)
    async def family_contact_error_handler(
        request: Request, exc: FamilyContactError
    ) -> JSONResponse:
        del request
        statuses = {
            "family_contact_exists": 409,
            "family_contact_not_found": 404,
            "notification_unavailable": 503,
        }
        messages = {
            "family_contact_exists": (
                "A family contact already exists. Update it instead."
            ),
            "family_contact_not_found": "No family contact has been nominated.",
            "notification_unavailable": (
                "The nomination was saved, but WhatsApp is temporarily unavailable."
            ),
        }
        return JSONResponse(
            status_code=statuses[exc.code],
            content={"error": exc.code, "message": messages[exc.code], "details": {}},
        )

    @api.exception_handler(ActivationError)
    async def activation_error_handler(
        request: Request, exc: ActivationError
    ) -> JSONResponse:
        del request
        statuses = {
            "activation_code_invalid": 404,
            "activation_code_already_used": 409,
            "activation_code_expired": 410,
            "activation_code_phone_mismatch": 403,
        }
        messages = {
            "activation_code_invalid": "This activation code is invalid.",
            "activation_code_already_used": (
                "This activation code has already been used."
            ),
            "activation_code_expired": "This activation code has expired.",
            "activation_code_phone_mismatch": (
                "This activation code was issued to a different phone number."
            ),
        }
        return JSONResponse(
            status_code=statuses[exc.code],
            content={"error": exc.code, "message": messages[exc.code], "details": {}},
        )

    @api.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    api.include_router(auth_router, prefix="/v1")
    api.include_router(admin_router, prefix="/v1")
    api.include_router(manifest_router, prefix="/v1")
    api.include_router(pricing_router, prefix="/v1")
    api.include_router(otp_webhook_router, prefix="/v1")
    api.include_router(profile_router, prefix="/v1")
    api.include_router(activation_router, prefix="/v1")
    return api


app = create_app()
