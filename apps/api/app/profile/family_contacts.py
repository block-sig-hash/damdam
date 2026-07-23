from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.auth.schemas import to_e164
from app.notifications.service import NotificationError, NotificationService
from app.profile.models import FamilyContact
from app.profile.schemas import FamilyContactCreate, FamilyContactUpdate


class FamilyContactError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class FamilyContactService:
    def __init__(
        self,
        notifications: NotificationService,
        clock: Callable[[], datetime],
    ) -> None:
        self.notifications = notifications
        self.clock = clock

    def create(
        self,
        session: Session,
        user_id: UUID,
        payload: FamilyContactCreate,
    ) -> FamilyContact:
        existing = self._get(session, user_id)
        if existing is not None:
            raise FamilyContactError("family_contact_exists")

        contact = FamilyContact(
            user_id=user_id,
            phone_number=to_e164(payload.phone_number),
            name=payload.name,
            locale=payload.locale,
        )
        try:
            session.add(contact)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise FamilyContactError("family_contact_exists") from exc
        session.refresh(contact)
        self._notify(session, contact)
        return contact

    def update(
        self,
        session: Session,
        user_id: UUID,
        payload: FamilyContactUpdate,
    ) -> FamilyContact:
        contact = self._get(session, user_id)
        if contact is None:
            raise FamilyContactError("family_contact_not_found")

        phone_number_input = (
            payload.phone_number if "phone_number" in payload.model_fields_set else None
        )
        if phone_number_input is not None:
            phone_number = to_e164(phone_number_input)
            if phone_number != contact.phone_number:
                contact.phone_number = phone_number
                contact.notified_of_nomination = False
        if "name" in payload.model_fields_set:
            contact.name = payload.name
        if "locale" in payload.model_fields_set and payload.locale is not None:
            contact.locale = payload.locale
        contact.updated_at = self.clock()
        session.add(contact)
        session.commit()
        session.refresh(contact)

        if phone_number_input is not None and not contact.notified_of_nomination:
            self._notify(session, contact)
        return contact

    @staticmethod
    def _get(session: Session, user_id: UUID) -> FamilyContact | None:
        return session.exec(
            select(FamilyContact).where(FamilyContact.user_id == user_id)
        ).first()

    def _notify(self, session: Session, contact: FamilyContact) -> None:
        try:
            self.notifications.send_family_nomination(
                contact.phone_number, contact.locale.value
            )
        except NotificationError as exc:
            raise FamilyContactError("notification_unavailable") from exc
        contact.notified_of_nomination = True
        contact.updated_at = self.clock()
        session.add(contact)
        session.commit()
        session.refresh(contact)
