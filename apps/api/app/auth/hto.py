import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID, uuid4

import bcrypt
import jwt
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.auth.models import (
    HTOApprovalStatus,
    Organization,
    OrganizationRefreshToken,
    OrganizationType,
)
from app.auth.schemas import HTORegistrationRequest, to_e164
from app.auth.tokens import decode_with_clock
from app.config import Settings
from app.notifications.service import NotificationError, NotificationService

_DUMMY_HASH = bcrypt.hashpw(b"invalid-password", bcrypt.gensalt(rounds=12))


class HTOAuthError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class HTOTokenPair:
    access_token: str
    refresh_token: str


class HTOService:
    def __init__(
        self,
        settings: Settings,
        notifications: NotificationService,
        clock: Callable[[], datetime],
    ) -> None:
        self.settings = settings
        self.notifications = notifications
        self.clock = clock

    def register(
        self, session: Session, payload: HTORegistrationRequest
    ) -> Organization:
        existing = session.exec(
            select(Organization).where(Organization.email == payload.email)
        ).first()
        if existing is not None:
            raise HTOAuthError("email_already_registered")

        organization = Organization(
            org_type=OrganizationType.HTO_OPERATOR,
            name=payload.business_name,
            primary_contact_name=payload.operator_name,
            email=payload.email,
            password_hash=bcrypt.hashpw(
                payload.password.encode(), bcrypt.gensalt(rounds=12)
            ).decode(),
            phone_number=to_e164(payload.phone_number),
            nahcon_licence_number=payload.nahcon_licence_number,
            locale=payload.locale,
        )
        try:
            session.add(organization)
            session.flush()
            verification_url = self._verification_url(organization)
            self.notifications.send_verification(
                organization.email,
                organization.primary_contact_name,
                verification_url,
                organization.locale.value,
            )
            session.commit()
        except NotificationError as exc:
            session.rollback()
            raise HTOAuthError("notification_unavailable") from exc
        except IntegrityError as exc:
            session.rollback()
            raise HTOAuthError("email_already_registered") from exc
        session.refresh(organization)
        return organization

    def _verification_url(self, organization: Organization) -> str:
        now = self.clock()
        token = jwt.encode(
            {
                "sub": str(organization.id),
                "aud": "hto_dashboard",
                "type": "email_verification",
                "email": organization.email,
                "iat": now,
                "exp": now
                + timedelta(hours=self.settings.hto_email_verification_ttl_hours),
            },
            self.settings.jwt_secret,
            algorithm="HS256",
        )
        query = urlencode({"token": token, "lang": organization.locale.value})
        return f"{self.settings.dashboard_base_url}/verify-email?{query}"

    def verify_email(self, session: Session, token: str) -> Organization:
        try:
            claims = decode_with_clock(
                token, self.settings.jwt_secret, "hto_dashboard", self.clock()
            )
            if claims.get("type") != "email_verification":
                raise HTOAuthError("invalid_verification_token")
            organization_id = UUID(claims["sub"])
        except HTOAuthError:
            raise
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise HTOAuthError("invalid_verification_token") from exc

        organization = session.get(Organization, organization_id)
        if organization is None or organization.email != claims.get("email"):
            raise HTOAuthError("invalid_verification_token")
        organization.email_verified = True
        session.add(organization)
        session.commit()
        session.refresh(organization)
        return organization

    def login(
        self, session: Session, email: str, password: str
    ) -> tuple[HTOTokenPair, Organization]:
        organization = session.exec(
            select(Organization).where(Organization.email == email)
        ).first()
        password_hash = (
            organization.password_hash.encode() if organization else _DUMMY_HASH
        )
        if not bcrypt.checkpw(password.encode(), password_hash) or organization is None:
            raise HTOAuthError("invalid_credentials")
        if organization.org_type != OrganizationType.HTO_OPERATOR:
            raise HTOAuthError("invalid_credentials")
        if not organization.email_verified:
            raise HTOAuthError("email_not_verified")
        if organization.approval_status == HTOApprovalStatus.PENDING:
            raise HTOAuthError("pending_approval")
        if organization.approval_status == HTOApprovalStatus.REJECTED:
            raise HTOAuthError("rejected")
        return self._issue_tokens(session, organization), organization

    def _issue_tokens(
        self, session: Session, organization: Organization
    ) -> HTOTokenPair:
        now = self.clock()
        access_expiry = now + timedelta(minutes=self.settings.jwt_access_ttl_minutes)
        refresh_expiry = now + timedelta(days=self.settings.jwt_refresh_ttl_days)
        access = jwt.encode(
            {
                "sub": str(organization.id),
                "aud": "hto_dashboard",
                "type": "access",
                "jti": str(uuid4()),
                "iat": now,
                "exp": access_expiry,
            },
            self.settings.jwt_secret,
            algorithm="HS256",
        )
        refresh_id = uuid4()
        refresh = jwt.encode(
            {
                "sub": str(organization.id),
                "aud": "hto_dashboard",
                "type": "refresh",
                "jti": str(refresh_id),
                "iat": now,
                "exp": refresh_expiry,
            },
            self.settings.jwt_secret,
            algorithm="HS256",
        )
        session.add(
            OrganizationRefreshToken(
                id=refresh_id,
                organization_id=organization.id,
                token_hash=hashlib.sha256(refresh.encode()).hexdigest(),
                expires_at=refresh_expiry,
            )
        )
        session.commit()
        return HTOTokenPair(access_token=access, refresh_token=refresh)

    def list_organizations(
        self, session: Session, status: HTOApprovalStatus | None
    ) -> list[Organization]:
        statement = select(Organization).where(
            Organization.org_type == OrganizationType.HTO_OPERATOR
        )
        if status is not None:
            statement = statement.where(Organization.approval_status == status)
        return list(
            session.exec(statement.order_by(col(Organization.created_at))).all()
        )

    def approve(
        self, session: Session, organization_id: UUID, admin_id: UUID
    ) -> Organization:
        organization = session.get(Organization, organization_id)
        if (
            organization is None
            or organization.org_type != OrganizationType.HTO_OPERATOR
        ):
            raise HTOAuthError("operator_not_found")
        if organization.approval_status == HTOApprovalStatus.REJECTED:
            raise HTOAuthError("invalid_approval_transition")
        if organization.approval_status == HTOApprovalStatus.PENDING:
            if not organization.email_verified:
                raise HTOAuthError("email_not_verified")
            organization.approval_status = HTOApprovalStatus.APPROVED
            organization.approved_at = self.clock()
            organization.approved_by = admin_id
            session.add(organization)
            session.commit()
            session.refresh(organization)

        notification_failed = False
        if organization.approval_email_sent_at is None:
            try:
                self.notifications.send_approval_email(
                    organization.email,
                    organization.primary_contact_name,
                    organization.locale.value,
                )
            except NotificationError:
                notification_failed = True
            else:
                organization.approval_email_sent_at = self.clock()
                session.add(organization)
                session.commit()
                session.refresh(organization)

        if organization.approval_whatsapp_sent_at is None:
            try:
                self.notifications.send_approval_whatsapp(
                    organization.phone_number,
                    organization.primary_contact_name,
                    organization.locale.value,
                )
            except NotificationError:
                notification_failed = True
            else:
                organization.approval_whatsapp_sent_at = self.clock()
                session.add(organization)
                session.commit()
                session.refresh(organization)

        if notification_failed:
            raise HTOAuthError("notification_unavailable")
        return organization

    def reject(
        self, session: Session, organization_id: UUID, admin_id: UUID, reason: str
    ) -> Organization:
        organization = session.get(Organization, organization_id)
        if (
            organization is None
            or organization.org_type != OrganizationType.HTO_OPERATOR
        ):
            raise HTOAuthError("operator_not_found")
        # Unlike approve(), reject() has no notification-retry need for an
        # already-processed organization, so any non-PENDING status is a
        # rejected transition — including an already-REJECTED one, so a
        # second reject() call can never silently discard the second
        # admin's reason/identity behind a misleadingly successful response.
        if organization.approval_status != HTOApprovalStatus.PENDING:
            raise HTOAuthError("invalid_approval_transition")
        organization.approval_status = HTOApprovalStatus.REJECTED
        organization.rejected_at = self.clock()
        organization.rejected_by = admin_id
        organization.rejection_reason = reason
        session.add(organization)
        session.commit()
        session.refresh(organization)
        return organization
