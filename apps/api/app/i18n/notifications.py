from dataclasses import dataclass
from decimal import Decimal
from html import escape

from app.i18n.catalog import normalize_locale


@dataclass(frozen=True)
class EmailContent:
    subject: str
    html: str


@dataclass(frozen=True)
class WhatsAppTemplate:
    name: str
    language: str


_MONTHS_FR = {
    "Jan": "janv.",
    "Feb": "févr.",
    "Mar": "mars",
    "Apr": "avr.",
    "May": "mai",
    "Jun": "juin",
    "Jul": "juil.",
    "Aug": "août",
    "Sep": "sept.",
    "Oct": "oct.",
    "Nov": "nov.",
    "Dec": "déc.",
}


class NotificationRenderer:
    """Turns vendor-neutral events into recipient-locale channel content."""

    def timestamp(self, value: str, locale: object) -> str:
        if normalize_locale(locale) != "fr":
            return value
        localized = value
        for english, french in _MONTHS_FR.items():
            localized = localized.replace(f" {english} ", f" {french} ")
        return localized

    def amount_ngn(self, amount: Decimal, locale: object) -> str:
        formatted = f"{amount:,.2f}"
        if normalize_locale(locale) == "fr":
            formatted = formatted.replace(",", "\u202f").replace(".", ",")
        return f"NGN {formatted}"

    def tier_name(self, value: str, locale: object) -> str:
        if normalize_locale(locale) != "fr":
            return value
        return {
            "Starter": "Découverte",
            "Basic": "Essentiel",
            "Standard": "Standard",
            "Family": "Famille",
        }.get(value, value)

    def email_sos(
        self,
        pilgrim_name: str,
        pilgrim_phone: str,
        timestamp: str,
        maps_url: str | None,
        cancelled: bool,
        locale: object,
    ) -> EmailContent:
        safe_name = escape(pilgrim_name)
        safe_phone = escape(pilgrim_phone)
        safe_time = escape(self.timestamp(timestamp, locale))
        if normalize_locale(locale) == "fr":
            subject = "SOS annulé" if cancelled else "URGENT : SOS d’un pèlerin"
            verb = (
                "a annulé son SOS"
                if cancelled
                else "a déclenché un SOS et a besoin d’aide"
            )
            location = (
                f'<p><a href="{escape(maps_url, quote=True)}">Voir la position</a></p>'
                if maps_url
                else "<p>Position indisponible.</p>"
            )
            return EmailContent(
                subject,
                f"<p>{safe_name} ({safe_phone}) {verb} à {safe_time}.</p>{location}",
            )
        subject = "SOS cancelled" if cancelled else "URGENT: pilgrim SOS"
        verb = "cancelled their SOS" if cancelled else "triggered an SOS and needs help"
        location = (
            f'<p><a href="{escape(maps_url, quote=True)}">View location</a></p>'
            if maps_url
            else "<p>Location unavailable.</p>"
        )
        return EmailContent(
            subject,
            f"<p>{safe_name} ({safe_phone}) {verb} at {safe_time}.</p>{location}",
        )

    def email_verification(
        self, operator_name: str, verification_url: str, locale: object
    ) -> EmailContent:
        name = escape(operator_name)
        url = escape(verification_url, quote=True)
        if normalize_locale(locale) == "fr":
            return EmailContent(
                "Vérifiez votre compte opérateur DamDam",
                f"<p>Bonjour {name},</p>"
                f'<p><a href="{url}">Vérifiez votre adresse e-mail</a>. '
                "Ce lien expire dans 24 heures.</p>",
            )
        return EmailContent(
            "Verify your DamDam operator account",
            f"<p>Hello {name},</p>"
            f'<p><a href="{url}">Verify your email address</a>. '
            "This link expires in 24 hours.</p>",
        )

    def email_approval(self, operator_name: str, locale: object) -> EmailContent:
        name = escape(operator_name)
        if normalize_locale(locale) == "fr":
            return EmailContent(
                "Votre compte opérateur DamDam est approuvé",
                f"<p>Bonjour {name}, votre compte opérateur DamDam est approuvé.</p>",
            )
        return EmailContent(
            "Your DamDam operator account is approved",
            f"<p>Hello {name}, your DamDam operator account is approved.</p>",
        )

    def email_invoice(
        self,
        operator_name: str,
        order_id: str,
        total_ngn: Decimal,
        locale: object,
    ) -> EmailContent:
        name = escape(operator_name)
        order = escape(order_id)
        amount = self.amount_ngn(total_ngn, locale)
        if normalize_locale(locale) == "fr":
            return EmailContent(
                f"Facture DamDam {order}",
                f"<p>Bonjour {name},</p><p>La facture de votre commande HTO "
                f"d’un montant de {amount} est jointe. Utilisez {order} comme "
                "référence du virement bancaire.</p>",
            )
        return EmailContent(
            f"DamDam invoice {order}",
            f"<p>Hello {name},</p><p>Your HTO order invoice for {amount} is "
            f"attached. Use {order} as the bank-transfer reference.</p>",
        )

    def email_receipt(
        self, tier_name: str, amount_ngn: Decimal, reference: str, locale: object
    ) -> EmailContent:
        tier = escape(self.tier_name(tier_name, locale))
        amount = self.amount_ngn(amount_ngn, locale)
        safe_reference = escape(reference)
        if normalize_locale(locale) == "fr":
            return EmailContent(
                "Votre reçu de paiement DamDam",
                f"<p>Paiement reçu pour votre formule {tier}.</p>"
                f"<p>Montant : {amount}<br>Référence : {safe_reference}</p>",
            )
        return EmailContent(
            "Your DamDam payment receipt",
            f"<p>Payment received for your {tier} package.</p>"
            f"<p>Amount: {amount}<br>Reference: {safe_reference}</p>",
        )

    def whatsapp_template(
        self, base_name: str, french_name: str, locale: object
    ) -> WhatsAppTemplate:
        language = normalize_locale(locale)
        return WhatsAppTemplate(
            french_name if language == "fr" and french_name else base_name,
            language,
        )

    def location_unavailable(self, locale: object) -> str:
        return (
            "Position indisponible"
            if normalize_locale(locale) == "fr"
            else "Location unavailable"
        )

    def push_sos(
        self, pilgrim_name: str, cancelled: bool, locale: object
    ) -> tuple[str, str]:
        if normalize_locale(locale) == "fr":
            return (
                "SOS annulé" if cancelled else "URGENT : SOS d’un pèlerin",
                (
                    f"{pilgrim_name} a annulé le SOS."
                    if cancelled
                    else f"{pilgrim_name} a besoin d’aide maintenant."
                ),
            )
        return (
            "SOS cancelled" if cancelled else "URGENT: pilgrim SOS",
            (
                f"{pilgrim_name} cancelled the SOS."
                if cancelled
                else f"{pilgrim_name} needs help now."
            ),
        )

    def sms_sos(
        self,
        pilgrim_name: str,
        timestamp: str,
        hto_phone: str,
        maps_url: str | None,
        cancelled: bool,
        locale: object,
    ) -> str:
        timestamp = self.timestamp(timestamp, locale)
        if normalize_locale(locale) == "fr":
            prefix = "SOS annulé" if cancelled else "URGENT"
            verb = (
                "a annulé son SOS"
                if cancelled
                else "a déclenché un SOS et a besoin d’aide"
            )
            message = (
                f"{prefix} : {pilgrim_name} {verb} à {timestamp}. "
                f"Contactez l’opérateur : {hto_phone}."
            )
        else:
            prefix = "SOS cancelled" if cancelled else "URGENT"
            verb = (
                "cancelled their SOS"
                if cancelled
                else "triggered an SOS and needs help"
            )
            message = (
                f"{prefix}: {pilgrim_name} {verb} at {timestamp}. "
                f"Contact the operator: {hto_phone}."
            )
        return f"{message} {maps_url}" if maps_url else message

    def sms_checkin(
        self, pilgrim_name: str, timestamp: str, maps_url: str | None, locale: object
    ) -> str:
        timestamp = self.timestamp(timestamp, locale)
        if normalize_locale(locale) == "fr":
            message = (
                f"{pilgrim_name} a confirmé être en sécurité à {timestamp}. "
                "Tout va bien."
            )
        else:
            message = f"{pilgrim_name} checked in safely at {timestamp}. All is well."
        return f"{message} {maps_url}" if maps_url else message
