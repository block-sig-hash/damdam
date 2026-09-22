from base64 import b64decode
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis import Redis

from app.account.routes import router as account_router
from app.account.service import AccountError, AccountService
from app.activation.routes import router as activation_router
from app.activation.service import ActivationError, ActivationService
from app.admin.routes import router as admin_router
from app.audit.service import AuditLogService
from app.auth.hto import HTOAuthError, HTOService
from app.auth.pin import PINService
from app.auth.routes import router as auth_router
from app.bulk.routes import recipient_router as bulk_recipient_router
from app.bulk.routes import router as bulk_router
from app.bulk.service import BulkError, BulkProvisioningService
from app.calling import account_deletion as _calling_account_deletion  # noqa: F401
from app.calling.charging import CallChargingService
from app.calling.contract import CallingAdapter, CallingError
from app.calling.lifecycle import CallLifecycleError, CallLifecycleService
from app.calling.routes import router as calling_router
from app.calling.routes import webhook_router as calling_webhook_router
from app.calling.service import CallAuthorizationError, CallAuthorizationService
from app.calling.sessions import ClientSessionError, ClientSessionService
from app.calling.telnyx import DisabledCallingAdapter, TelnyxCallingAdapter
from app.catalog.service import CatalogError, CatalogService
from app.checkins.routes import router as checkin_router
from app.checkout.catalog_view import CatalogViewService
from app.checkout.routes import catalog_router, checkout_router, quote_router
from app.checkout.routes import order_router as consumer_order_router
from app.checkout.service import CheckoutError, CheckoutService
from app.config import Settings, get_settings
from app.connectivity.credentials import CredentialVault
from app.connectivity.service import ConnectivityService
from app.consumer.routes import invitation_preview_router
from app.consumer.routes import router as consumer_router
from app.consumer.service import ConsumerService
from app.container import (
    CeleryEsimIssuanceScheduler,
    CeleryProvisioningScheduler,
    build_notification_service,
    build_otp_service,
    build_payment_providers,
    default_dependencies,
)
from app.controls.service import ControlService
from app.db import SessionFactory
from app.enterprise.offboarding import OffboardingError, OffboardingService
from app.enterprise.reporting import EnterpriseReportingService
from app.enterprise.routes import router as enterprise_router
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
from app.fulfilment.service import FulfilmentService
from app.health import LivenessResponse, ReadinessResponse, check_readiness
from app.i18n import api_message, localize_validation_errors, request_locale
from app.identity.delivery import (
    DeliveryTransport,
    NullDeliveryTransport,
    RecordingDeliveryTransport,
)
from app.identity.service import IdentityError, IdentityService
from app.ledger.service import LedgerService
from app.line.routes import router as line_router
from app.line.service import LineError, LineViewService
from app.manifests.invoices import InvoiceStorage, build_invoice_storage
from app.manifests.orders import ManifestOrderService, ProvisioningScheduler
from app.manifests.routes import pricing_router
from app.manifests.routes import router as manifest_router
from app.manifests.service import ManifestError, ManifestService
from app.mfa.service import MfaError, MfaService
from app.monitoring import PostHogExceptionMiddleware, build_exception_tracker
from app.notifications.service import EmailSender, WhatsAppSender
from app.operations.routes import router as operations_router
from app.operations.service import OperationsError, OperationsService
from app.operations.support import SupportDirectory
from app.organizations.invitations import InvitationError, InvitationService
from app.organizations.routes import invitation_router
from app.organizations.routes import mfa_router as organization_mfa_router
from app.organizations.routes import router as organization_router
from app.organizations.service import MembershipError, MembershipService
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
from app.payments.routing import PaymentRouter, PaymentRoutingError
from app.payments.service import PaymentError, PaymentService
from app.people.routes import router as people_router
from app.people.service import PeopleError, PeopleService
from app.pricing.routes import router as retail_pricing_router
from app.pricing.service import RetailPricingService
from app.profile.device_tokens import DeviceTokenService
from app.profile.routes import router as profile_router
from app.reports.routes import router as reports_router
from app.reports.service import ProvisioningReportService
from app.retention.service import RetentionService
from app.retirement import RetiredFeatureError
from app.sos.routes import router as sos_router
from app.usage.service import UsageService
from app.voice.providers import TelnyxVoiceProvider, VoiceProvider
from app.voice.routes import router as voice_router
from app.voice.service import VoiceError, VoiceService


def _build_credential_vault(
    settings: Settings, clock: Callable[[], datetime]
) -> CredentialVault | None:
    """A vault, or `None` and a deployment that cannot deliver profiles.

    `None` is deliberate and is not a degraded mode to paper over: without a
    key there is nothing to unseal, and the alternative — a built-in default —
    would seal one-time-use eSIM profiles under a key that is not a secret. The
    delivery endpoints refuse with `installation_material_unavailable`, which
    says which way it failed.
    """
    if not settings.activation_material_key:
        return None
    return CredentialVault(
        b64decode(settings.activation_material_key, validate=True),
        settings.activation_material_key_reference,
        clock=clock,
    )


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
    calling_adapter: CallingAdapter | None = None,
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
    api.state.membership_service = MembershipService(clock)
    api.state.invitation_service = InvitationService(
        memberships=api.state.membership_service, clock=clock
    )
    api.state.consumer_service = ConsumerService(clock=clock)
    api.state.catalog_service = CatalogService(clock=clock)
    api.state.catalog_view_service = CatalogViewService(
        api.state.catalog_service, clock=clock
    )
    api.state.checkout_service = CheckoutService(
        api.state.catalog_service, PaymentRouter(clock=clock), clock=clock
    )
    # D4 is open, so no processor adapter is registered. `None` is the
    # current state of the decision, not a missing wire-up: naming a
    # candidate here would be a selection sitting in code.
    api.state.payment_processor_adapter = None
    # Chunks 15-17 shipped the connectivity lifecycle, usage reconciliation and
    # spending controls as services with no HTTP surface and no wiring. Chunk 20
    # is the first thing that needs them at request time, so this is where they
    # are constructed.
    api.state.credential_vault = _build_credential_vault(resolved_settings, clock)
    api.state.connectivity_service = ConnectivityService(
        FulfilmentService(clock=clock),
        vault=api.state.credential_vault,
        clock=clock,
    )
    api.state.usage_service = UsageService(LedgerService(clock=clock), clock=clock)
    api.state.control_service = ControlService(
        api.state.usage_service,
        api.state.connectivity_service,
        LedgerService(clock=clock),
        clock=clock,
    )
    api.state.line_service = LineViewService(
        api.state.usage_service,
        controls=api.state.control_service,
        vault=api.state.credential_vault,
        connectivity=api.state.connectivity_service,
        clock=clock,
        internet_dialer_enabled=resolved_settings.internet_dialer_enabled,
    )
    api.state.account_service = AccountService(clock=clock)
    api.state.otp_service.tokens.session_tracker = api.state.account_service
    api.state.people_service = PeopleService(clock=clock)
    # Bulk provisioning shares the application clock with everything else that
    # moves money, so a hold and the order that spends it cannot disagree about
    # when.
    #
    # The shared connectivity service grants internet-only allowances. Carrier
    # provisioning additionally requires an approved adapter and the durable
    # begin/commit/dispatch/reconcile sequence. No adapter is selected while D1
    # is open, so carrier items stay ordered instead of being mislabeled
    # provisioned; internet-only items can still receive their local grant.
    api.state.bulk_service = BulkProvisioningService(
        LedgerService(clock=clock),
        connectivity=api.state.connectivity_service,
        carrier_provisioning_confirmed=False,
        clock=clock,
    )
    # Enterprise funding, reporting and offboarding share the same ledger clock.
    # Reporting owns no tables: it reads the ledger, chunk 17's policies, chunk
    # 22's structure and chunk 16's usage, because a stored report starts
    # drifting from the books the moment it is written.
    api.state.enterprise_reporting_service = EnterpriseReportingService(
        LedgerService(clock=clock), clock=clock
    )
    api.state.mfa_service = MfaService(clock)
    api.state.hto_pilgrim_service = HtoPilgrimService()
    api.state.report_service = ProvisioningReportService(clock)
    api.state.voice_service = VoiceService(
        resolved_settings,
        voice_provider or TelnyxVoiceProvider(resolved_settings),
        clock,
        cast(RedisClient, redis_client),
    )

    # --- outbound internet calling (US-45, chunk V02) ----------------------
    #
    # Keep the provider adapter when either provider-side control or webhook
    # verification remains configured. Its originate/session methods still
    # enforce the live-route gate, while hangup, credential revocation and
    # signed terminal events must continue after new calling is switched off.
    # A deployment with no provider configuration gets the honest disabled
    # adapter.
    resolved_calling_adapter: CallingAdapter = calling_adapter or (
        TelnyxCallingAdapter(resolved_settings, clock=clock)
        if resolved_settings.telnyx_api_key or resolved_settings.telnyx_public_key
        else DisabledCallingAdapter()
    )
    api.state.calling_adapter = resolved_calling_adapter
    if calling_adapter is not None and resolved_settings.app_env != "test":
        raise ValueError("Injected calling adapters are test-only")
    # The outbound identity is chosen by the server from numbers we own. Own-
    # number presentation is deferred (VOICE-EXPANSION.md) and unproven on this
    # route, so there is no request field a client could ask for one through.
    api.state.calling_identity_e164 = (
        resolved_settings.calling_outbound_identity_e164
    )
    api.state.call_authorization_service = CallAuthorizationService(
        LedgerService(clock=clock),
        clock=clock,
        supported_countries=frozenset(
            country.upper()
            for country in resolved_settings.calling_supported_destination_countries
        ),
        grant_ttl_seconds=resolved_settings.calling_grant_ttl_seconds,
        max_call_seconds=resolved_settings.calling_max_call_seconds,
        route_enabled=resolved_settings.calling_live_routes_enabled,
    )
    api.state.client_session_service = ClientSessionService(
        resolved_calling_adapter,
        clock=clock,
        sessions_per_hour=resolved_settings.calling_sessions_per_device_per_hour,
    )
    # V03: settlement. Constructed with the same ledger clock as authorization
    # so a hold and the charge that spends it cannot disagree about when.
    api.state.call_charging_service = CallChargingService(
        LedgerService(clock=clock),
        controls=api.state.control_service,
        clock=clock,
        supplier_cost_wait_seconds=(
            resolved_settings.calling_supplier_cost_wait_seconds
        ),
    )
    api.state.call_lifecycle_service = CallLifecycleService(
        resolved_calling_adapter,
        api.state.call_authorization_service,
        clock=clock,
        charging=api.state.call_charging_service,
    )
    api.state.membership_service.add_revocation_listener(
        api.state.call_lifecycle_service
    )
    api.state.offboarding_service = OffboardingService(
        LedgerService(clock=clock),
        clock=clock,
        memberships=api.state.membership_service,
        mfa=api.state.mfa_service,
        call_revoker=api.state.call_lifecycle_service.on_membership_revoked,
    )
    # The internal operations surface owns only its immutable audit trail. Its
    # constrained actions reuse the accepted ledger and calling services.
    api.state.operations_service = OperationsService(
        LedgerService(clock=clock), clock=clock
    )
    api.state.support_directory = SupportDirectory(api.state.operations_service)
    api.state.identity_service.add_recovery_listener(
        api.state.client_session_service
    )

    @api.exception_handler(CallAuthorizationError)
    async def call_authorization_error_handler(
        request: Request, exc: CallAuthorizationError
    ) -> JSONResponse:
        statuses = {
            # `attempt_not_found` covers somebody else's attempt as well as one
            # that does not exist. A distinct 403 would confirm that an id is
            # real, which is enough to enumerate other customers' calls.
            "attempt_not_found": 404,
            "not_a_member": 403,
            "device_not_authorized": 403,
            "entitlement_not_available": 403,
            "attempt_expired": 410,
            "idempotency_conflict": 409,
            "insufficient_funds": 409,
            "attempt_not_startable": 409,
            "reservation_failed": 409,
            # 503, not 400: the request is well formed and the route is off.
            # A 4xx would tell a client to change its request, and no request
            # it can make will work while B1-B5 are open.
            "calling_route_disabled": 503,
            # Destination refusals are about the world, not about the syntax of
            # the request, so they are 409 apart from the one that really is a
            # malformed number.
            "destination_not_e164": 400,
            "destination_emergency_or_special": 409,
            "destination_premium": 409,
            "destination_country_not_supported": 409,
            "destination_country_unknown": 409,
            "rate_unavailable": 409,
            "rate_unusable": 409,
            "invalid_duration": 400,
        }
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(ClientSessionError)
    async def client_session_error_handler(
        request: Request, exc: ClientSessionError
    ) -> JSONResponse:
        statuses = {
            "device_id_required": 400,
            "session_rate_limited": 429,
            # An unknown outcome is not a failure and not a success. 409 says
            # "the state is unresolved", and the client must not retry into a
            # second orphaned credential.
            "session_outcome_unknown": 409,
            "calling_route_disabled": 503,
        }
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(CallingError)
    async def calling_provider_error_handler(
        request: Request, exc: CallingError
    ) -> JSONResponse:
        statuses = {
            # A bad signature gets 401 and nothing else. No detail, because the
            # sender of an unverifiable event is not somebody to help debug.
            "invalid_webhook_signature": 401,
            "webhook_verification_unconfigured": 401,
            "invalid_webhook_payload": 400,
            "calling_route_disabled": 503,
            "capability_not_available": 503,
            "telnyx_not_configured": 503,
            "provider_rejected": 502,
            "invalid_provider_response": 502,
            "credential_expiry_unknown": 502,
        }
        return JSONResponse(
            status_code=statuses.get(exc.code, 502),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(CallLifecycleError)
    async def call_lifecycle_error_handler(
        request: Request, exc: CallLifecycleError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
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

    @api.exception_handler(CatalogError)
    async def catalog_error_handler(
        request: Request, exc: CatalogError
    ) -> JSONResponse:
        statuses = {
            "market_unavailable": 404,
            "product_unavailable": 404,
            "quote_not_found": 404,
            "quote_expired": 410,
            "quote_already_redeemed": 409,
            "quote_void": 409,
            "quote_tampered": 409,
            "empty_quote": 400,
            "invalid_quantity": 400,
            "currency_unsupported": 400,
            # Eligibility refusals are 409, not 400: the request is well formed
            # and the answer is about the world, not about the request.
            "no_verified_supplier": 409,
            "supplier_capability_mismatch": 409,
            "coverage_unavailable": 409,
            "device_rule_missing": 409,
            "device_not_checked": 409,
            "device_not_esim_capable": 409,
            "device_locked": 409,
            "price_unavailable": 409,
            "tariff_unavailable": 409,
            "market_not_verified": 409,
        }
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(CheckoutError)
    async def checkout_error_handler(
        request: Request, exc: CheckoutError
    ) -> JSONResponse:
        statuses = {
            "order_not_found": 404,
            "merchant_not_found": 409,
            "quote_already_redeemed": 409,
            "quote_not_yours": 403,
            "quote_empty": 400,
        }
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(PaymentRoutingError)
    async def payment_routing_error_handler(
        request: Request, exc: PaymentRoutingError
    ) -> JSONResponse:
        statuses = {
            # 409, not 500: nothing is broken. Collection is switched off until
            # D3 names a seller and D4 names a processor, and the app has to be
            # able to say so.
            "live_collection_disabled": 409,
            "no_merchant_account": 409,
            "payment_method_not_supported": 409,
            "ambiguous_merchant_route": 409,
            "attempt_in_progress": 409,
            "wrong_processor": 409,
            "currency_mismatch": 409,
            "already_paid": 409,
            "intent_not_found": 404,
            "merchant_not_found": 404,
        }
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(AccountError)
    async def account_error_handler(
        request: Request, exc: AccountError
    ) -> JSONResponse:
        statuses = {
            # 404 rather than 403 throughout. "Is not yours" and "does not
            # exist" have to be indistinguishable, or an id becomes an oracle
            # for enumerating other customers' sessions, orders and lines.
            "session_not_found": 404,
            "receipt_not_found": 404,
            "order_not_found": 404,
            "entitlement_not_found": 404,
            # 503: nothing is broken and retrying later works. A reference
            # space that could not produce a free value is a capacity answer.
            "support_reference_unavailable": 503,
            "account_deletion_blocked": 409,
        }
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(LineError)
    async def line_error_handler(
        request: Request, exc: LineError
    ) -> JSONResponse:
        statuses = {
            # Not 403. "Is not yours" and "does not exist" must be
            # indistinguishable, or the id becomes an oracle.
            "line_not_found": 404,
            "bank_receipt_not_found": 404,
            "call_charge_not_found": 404,
            "call_attempt_not_found": 404,
            "profile_not_issued": 409,
            # 503, not 500: nothing is broken. The deployment has no activation
            # key, so no profile can be delivered, and that is a configuration
            # answer an operator can act on.
            "installation_material_unavailable": 503,
            "installation_reporting_unavailable": 503,
            # One status and one message for expired, spent, wrong-account and
            # never-existed.
            "grant_not_redeemable": 409,
        }
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(OffboardingError)
    async def offboarding_error_handler(
        request: Request, exc: OffboardingError
    ) -> JSONResponse:
        statuses = {
            # 404 for anything belonging to another tenant, so an id cannot be
            # used to confirm that an organization employs somebody.
            "person_not_found": 404,
            "offboarding_not_found": 404,
            "last_owner": 409,
        }
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(BulkError)
    async def bulk_error_handler(
        request: Request, exc: BulkError
    ) -> JSONResponse:
        statuses = {
            "job_not_found": 404,
            "item_not_found": 404,
            "product_not_found": 404,
            "market_not_found": 404,
            "activation_request_not_found": 404,
            # 409 for "the world is not in the state this asks for", which is
            # every one of these: a spent token, a provisioned line somebody is
            # trying to cancel, an unknown outcome nobody has reconciled.
            "activation_request_spent": 409,
            "activation_request_revoked": 409,
            "activation_request_expired": 410,
            "activation_request_exists": 409,
            "item_already_provisioned": 409,
            "item_outcome_unknown": 409,
            "item_not_awaiting_supplier": 409,
            "recipient_archived": 409,
            "line_not_ready": 409,
            "job_not_fundable": 409,
            "job_not_provisionable": 409,
            "idempotency_conflict": 409,
            # 503: nothing is broken and an operator can act on it. D3 is open,
            # so a published market may genuinely have no seller recorded yet.
            "market_has_no_seller": 503,
        }
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(OperationsError)
    async def operations_error_handler(
        request: Request, exc: OperationsError
    ) -> JSONResponse:
        statuses = {
            "supplier_attempt_not_found": 404,
            "exception_not_found": 404,
            "ledger_account_not_found": 404,
            "line_not_found": 404,
            # 409 for "the world is not in the state this action assumes".
            # `reconciliation_required` is the one that matters: the caller has
            # not asserted that anybody asked the supplier what happened, and
            # retrying the request unchanged must not succeed.
            "reconciliation_required": 409,
            "provider_reference_required": 409,
            "supplier_success_not_adopted": 409,
            "supplier_failure_has_adopted_service": 409,
            "attempt_already_settled": 409,
            "idempotency_conflict": 409,
            "exception_subject_mismatch": 409,
            "exception_already_resolved": 409,
            "exception_kind_mismatch": 409,
            "exception_requires_resolution": 409,
            "bank_receipt_not_unmatched": 409,
            "invalid_customer_account": 409,
            "cross_currency_compensation": 409,
            # 400: the request itself is malformed, not the world.
            "one_identifier_required": 400,
            "non_positive_amount": 400,
        }
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(PeopleError)
    async def people_error_handler(
        request: Request, exc: PeopleError
    ) -> JSONResponse:
        statuses = {
            # 404 throughout for anything that belongs to another tenant, so an
            # id cannot be used to confirm that an organization has a person.
            "person_not_found": 404,
            "import_not_found": 404,
            "cost_centre_not_found": 404,
            "team_exists": 409,
            "cost_centre_exists": 409,
            "import_already_applied": 409,
            "import_not_applicable": 409,
        }
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(MembershipError)
    async def membership_error_handler(
        request: Request, exc: MembershipError
    ) -> JSONResponse:
        statuses = {
            # 403, never 404: the caller authenticated, and telling them an
            # organization "does not exist" versus "is not yours" is the same
            # cross-tenant oracle AC-29.4 is about.
            "not_a_member": 403,
            "permission_denied": 403,
            "membership_not_found": 404,
            "role_change_forbidden": 403,
            "cannot_modify_own_membership": 409,
            "last_owner": 409,
            "already_a_member": 409,
            "organization_not_selected": 400,
            "shared_credential_forbidden": 403,
            "mfa_required": 403,
            "mfa_enrollment_required": 403,
            "mfa_locked": 423,
        }
        return JSONResponse(
            status_code=statuses.get(exc.code, 403),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(InvitationError)
    async def invitation_error_handler(
        request: Request, exc: InvitationError
    ) -> JSONResponse:
        statuses = {
            "invitation_invalid": 400,
            "invitation_expired": 410,
            "invitation_not_found": 404,
            "invitation_already_pending": 409,
            "invitation_recipient_mismatch": 403,
            "permission_denied": 403,
            "role_change_forbidden": 403,
            "already_a_member": 409,
            "not_a_member": 403,
        }
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": {},
            },
        )

    @api.exception_handler(MfaError)
    async def mfa_error_handler(request: Request, exc: MfaError) -> JSONResponse:
        statuses = {
            "mfa_not_enrolled": 409,
            "mfa_already_enrolled": 409,
            "mfa_code_invalid": 400,
            "mfa_code_replayed": 409,
            "mfa_locked": 423,
            "mfa_required": 403,
            "mfa_enrollment_required": 403,
            "not_a_member": 403,
        }
        details: dict[str, Any] = {}
        headers: dict[str, str] = {}
        if exc.retry_after is not None:
            details["retry_after"] = exc.retry_after
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=statuses.get(exc.code, 400),
            content={
                "error": exc.code,
                "message": api_message(request, exc.code),
                "details": details,
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
    api.include_router(organization_router, prefix="/v1")
    api.include_router(people_router, prefix="/v1")
    api.include_router(bulk_router, prefix="/v1")
    api.include_router(bulk_recipient_router, prefix="/v1")
    api.include_router(enterprise_router, prefix="/v1")
    api.include_router(operations_router, prefix="/v1")
    api.include_router(invitation_router, prefix="/v1")
    api.include_router(invitation_preview_router, prefix="/v1")
    api.include_router(consumer_router, prefix="/v1")
    api.include_router(catalog_router, prefix="/v1")
    api.include_router(quote_router, prefix="/v1")
    api.include_router(checkout_router, prefix="/v1")
    api.include_router(consumer_order_router, prefix="/v1")
    api.include_router(line_router, prefix="/v1")
    api.include_router(account_router, prefix="/v1")
    api.include_router(organization_mfa_router, prefix="/v1")
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
    api.include_router(calling_router, prefix="/v1")
    api.include_router(calling_webhook_router, prefix="/v1")
    api.include_router(checkin_router, prefix="/v1")
    api.include_router(sos_router, prefix="/v1")
    return api


app = create_app()
