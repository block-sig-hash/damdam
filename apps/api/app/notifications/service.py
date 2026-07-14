from decimal import Decimal
from typing import Protocol


class EmailSender(Protocol):
    def send_verification(
        self, email: str, operator_name: str, verification_url: str
    ) -> None: ...

    def send_approval(self, email: str, operator_name: str) -> None: ...

    def send_invoice(
        self,
        email: str,
        operator_name: str,
        order_id: str,
        total_ngn: Decimal,
        pdf: bytes,
    ) -> None: ...


class WhatsAppSender(Protocol):
    def send_approval(self, phone_number: str, operator_name: str) -> None: ...

    def send_family_nomination(self, phone_number: str) -> None: ...

    def send_activation(
        self, phone_number: str, pilgrim_name: str, tier_name: str, url: str
    ) -> None: ...


class NotificationError(Exception):
    pass


class NotificationService:
    def __init__(self, email: EmailSender, whatsapp: WhatsAppSender) -> None:
        self.email = email
        self.whatsapp = whatsapp

    def send_verification(
        self, email: str, operator_name: str, verification_url: str
    ) -> None:
        self.email.send_verification(email, operator_name, verification_url)

    def send_approval_email(self, email: str, operator_name: str) -> None:
        self.email.send_approval(email, operator_name)

    def send_approval_whatsapp(
        self, phone_number: str, operator_name: str
    ) -> None:
        self.whatsapp.send_approval(phone_number, operator_name)

    def send_family_nomination(self, phone_number: str) -> None:
        self.whatsapp.send_family_nomination(phone_number)

    def send_invoice(
        self,
        email: str,
        operator_name: str,
        order_id: str,
        total_ngn: Decimal,
        pdf: bytes,
    ) -> None:
        self.email.send_invoice(
            email, operator_name, order_id, total_ngn, pdf
        )

    def send_activation(
        self, phone_number: str, pilgrim_name: str, tier_name: str, url: str
    ) -> None:
        self.whatsapp.send_activation(phone_number, pilgrim_name, tier_name, url)
