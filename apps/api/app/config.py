import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ESIM_ACCESS_PACKAGE_CODE_KEY = re.compile(r"^[A-Z]{2}:\d+$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "postgresql+psycopg://damdam:damdam@localhost:5432/damdam"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = Field(
        default="development-only-secret-change-before-deploy",
        min_length=32,
    )
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 30

    posthog_api_key: str = ""
    posthog_host: str = "https://us.i.posthog.com"

    otp_provider_primary: Literal["termii", "twilio"] = "termii"
    otp_provider_secondary: Literal["termii", "twilio"] = "twilio"
    otp_failover_threshold_seconds: int = 180
    otp_request_timeout_seconds: int = 10
    otp_ttl_seconds: int = 600
    otp_attempt_limit: int = 3
    otp_lockout_seconds: int = 60
    otp_resend_cooldown_seconds: int = 30
    otp_requests_per_hour: int = 3

    termii_base_url: str = "https://api.ng.termii.com"
    termii_api_key: str = ""
    termii_sender_id: str = "DamDam"
    termii_webhook_secret: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_verify_service_sid: str = ""

    dashboard_base_url: str = "http://localhost:3000"
    hto_email_verification_ttl_hours: int = 24
    notification_timeout_seconds: int = 10
    resend_api_key: str = ""
    resend_from_email: str = "DamDam <operators@damdam.app>"
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v23.0"
    whatsapp_approval_template: str = "hto_account_approved"
    whatsapp_family_nomination_template: str = "family_contact_nominated"
    whatsapp_activation_template: str = "hto_package_activation"
    whatsapp_receipt_template: str = "retail_payment_receipt"
    whatsapp_esim_ready_template: str = "esim_profile_ready"
    whatsapp_checkin_template: str = "pilgrim_safe_checkin"
    whatsapp_sos_template: str = "pilgrim_urgent_sos"
    whatsapp_sos_cancelled_template: str = "pilgrim_sos_cancelled"
    firebase_project_id: str = ""
    firebase_access_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_webhook_verify_token: str = ""
    family_notify_channel_primary: Literal["whatsapp", "sms"] = "whatsapp"
    family_notify_channel_secondary: Literal["whatsapp", "sms"] = "sms"
    family_notify_fallback_seconds: int = 60
    activation_base_url: str = "https://damdam.app/activate"

    payment_processor_primary: Literal["paystack", "flutterwave"] = "paystack"
    payment_processor_secondary: Literal["paystack", "flutterwave"] = "flutterwave"
    payment_request_timeout_seconds: int = 15
    payment_callback_url: str = "https://damdam.app/payment/callback"
    paystack_base_url: str = "https://api.paystack.co"
    paystack_secret_key: str = ""
    flutterwave_base_url: str = "https://api.flutterwave.com"
    flutterwave_secret_key: str = ""
    flutterwave_webhook_hash: str = ""

    esim_vendor_primary: Literal["monty_mobile", "esim_access", "1global"] = (
        "monty_mobile"
    )
    esim_vendor_secondary: Literal["monty_mobile", "esim_access", "1global"] = (
        "esim_access"
    )
    esim_vendor_tertiary: Literal["monty_mobile", "esim_access", "1global"] = "1global"
    esim_request_timeout_seconds: int = 20
    monty_mobile_base_url: str = ""
    monty_mobile_api_key: str = ""
    esim_access_base_url: str = "https://api.esimaccess.com"
    esim_access_access_code: str = ""
    esim_access_secret_key: str = ""
    esim_access_package_codes: dict[str, str] = Field(default_factory=dict)
    esim_access_allocation_timeout_seconds: int = 35
    oneglobal_base_url: str = ""
    oneglobal_api_key: str = ""

    telnyx_base_url: str = "https://api.telnyx.com/v2"
    telnyx_api_key: str = ""
    telnyx_connection_id: str = ""
    telnyx_public_key: str = ""
    voice_request_timeout_seconds: int = 15
    telnyx_webhook_tolerance_seconds: int = 300

    # docs/verified-cli-scoping.md §4/§5 — CLI verification hardening
    # (data-model.md §6.40). NIN identity verification and the IDT Express
    # migration are both deliberately unresolved founder/product decisions;
    # these flags default off/unsupported rather than assume an answer.
    nin_verification_enabled: bool = False
    strict_nin_msisdn_match_required: bool = False
    idt_calling_enabled: bool = False
    cli_verification_max_attempts_per_window: int = 5
    cli_verification_rate_limit_window_seconds: int = 3600
    cli_verification_reference_ttl_seconds: int = 600
    cli_pending_idempotency_ttl_seconds: int = 120

    invoice_storage_backend: Literal["filesystem", "s3"] = "filesystem"
    invoice_storage_path: str = "/tmp/damdam-invoices"
    invoice_s3_endpoint_url: str = ""
    invoice_s3_access_key_id: str = ""
    invoice_s3_secret_access_key: str = ""
    invoice_s3_bucket: str = ""
    invoice_s3_region: str = "auto"
    invoice_bank_name: str = "Configure bank name"
    invoice_account_name: str = "DamDam Nigeria"
    invoice_account_number: str = "Configure account number"

    @model_validator(mode="after")
    def idt_calling_is_not_yet_supported(self) -> "Settings":
        # prd.md §5.5: IDT Express is a deliberate Phase 2+ cost-optimization
        # migration, not implemented today. Failing loudly at startup if
        # someone flips this on prevents a silent no-op deploy the way
        # ESIM_ACCESS_PACKAGE_CODES' old-format check does elsewhere.
        if self.idt_calling_enabled:
            raise ValueError(
                "IDT_CALLING_ENABLED is not supported yet -- IDT Express "
                "termination is a Phase 2+ item (prd.md §5.5), not "
                "implemented by this codebase"
            )
        return self

    @model_validator(mode="after")
    def s3_invoice_storage_must_be_configured(self) -> "Settings":
        if self.invoice_storage_backend == "s3" and not all(
            (
                self.invoice_s3_endpoint_url,
                self.invoice_s3_access_key_id,
                self.invoice_s3_secret_access_key,
                self.invoice_s3_bucket,
            )
        ):
            raise ValueError(
                "S3 invoice storage requires endpoint, credentials, and bucket"
            )
        return self

    @model_validator(mode="after")
    def providers_must_differ(self) -> "Settings":
        if self.otp_provider_primary == self.otp_provider_secondary:
            raise ValueError("OTP primary and secondary providers must differ")
        return self

    @model_validator(mode="after")
    def payment_processors_must_differ(self) -> "Settings":
        if self.payment_processor_primary == self.payment_processor_secondary:
            raise ValueError("Payment primary and secondary processors must differ")
        return self

    @model_validator(mode="after")
    def family_notification_channels_must_differ(self) -> "Settings":
        if self.family_notify_channel_primary == self.family_notify_channel_secondary:
            raise ValueError("Family notification channels must differ")
        return self

    @model_validator(mode="after")
    def esim_vendors_must_be_distinct(self) -> "Settings":
        vendors = {
            self.esim_vendor_primary,
            self.esim_vendor_secondary,
            self.esim_vendor_tertiary,
        }
        if len(vendors) != 3:
            raise ValueError(
                "eSIM primary, secondary, and tertiary vendors must differ"
            )
        return self

    @model_validator(mode="after")
    def esim_access_package_codes_must_use_composite_keys(self) -> "Settings":
        # data-model.md §6.36: keys changed from a bare data_gb integer
        # (e.g. "5") to a "COUNTRY:GB" composite (e.g. "SA:5") so eSIM
        # Access can be destination-aware. The old integer-style key is
        # still valid JSON (JSON object keys are always strings), so an
        # un-updated production env var parses without error and simply
        # never matches EsimAccessProvider's lookup -- every tier quietly
        # reports "not configured", and the vendor cascade to Monty
        # Mobile/1GLOBAL masks the failure from anyone not reading the
        # per-attempt log. Failing at startup instead of at first request
        # turns that into an immediate, unmissable deploy failure.
        if not self.esim_access_package_codes:
            return self
        bad_keys = sorted(
            key
            for key in self.esim_access_package_codes
            if not _ESIM_ACCESS_PACKAGE_CODE_KEY.match(key)
        )
        if bad_keys:
            raise ValueError(
                "ESIM_ACCESS_PACKAGE_CODES keys must use the 'COUNTRY:GB' "
                "composite format introduced by data-model.md §6.36 (e.g. "
                f"'SA:5'), not a bare data_gb key. Invalid key(s): {bad_keys}"
            )
        # The "at least one SA: entry" rule below bakes in today's real
        # business fact -- SA is the only destination ever sold -- the
        # same trigger data-model.md §6.20 names for revisiting bundled
        # single-destination content elsewhere in the codebase. When a
        # real second destination is onboarded, this check needs to
        # change from "must contain SA:" to something destination-aware
        # (e.g. "must contain an entry for the purchasing user's
        # destination"), not be silently satisfied or removed.
        if not any(
            key.startswith("SA:") for key in self.esim_access_package_codes
        ):
            raise ValueError(
                "ESIM_ACCESS_PACKAGE_CODES is configured but has no 'SA:' "
                "entries; SA is the only real destination sold today, so "
                "eSIM Access would have no usable package code and would "
                "silently report every tier as unconfigured"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
