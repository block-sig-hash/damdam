# ruff: noqa: E501

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from fastapi import Request

EN = "en"
FR = "fr"

_API_EN = {
    "feature_retired": "This feature is no longer part of DamDam. Please update the app to the latest version.",
    "checkin_rate_limited": "You can check in once every 15 minutes.",
    "checkin_id_conflict": "This check-in identifier is already in use.",
    "invalid_webhook_signature": "Webhook signature is invalid.",
    "invalid_webhook_payload": "Webhook payload is invalid.",
    "aggregator_unavailable": "eSIM issuance is queued and will retry automatically.",
    "package_not_found": "The package was not found.",
    "package_not_active": "The package is not active yet.",
    "esim_profile_not_found": "The eSIM profile has not been issued yet.",
    "invalid_otp": "The verification code is incorrect.",
    "otp_expired": "The verification code has expired.",
    "rate_limited": "Please wait before requesting another code.",
    "locked": "Too many attempts. Please wait before trying again.",
    "account_exists": "This number already has an account. Please log in.",
    "account_not_found": "No account exists for this phone number.",
    "otp_unavailable": "Verification is temporarily unavailable.",
    "invalid_refresh_token": "The refresh token is invalid or expired.",
    "pin_too_weak": "Choose a non-repeated, non-sequential 4-digit PIN.",
    "invalid_pin": "The PIN is incorrect.",
    "pin_not_set": "Set a PIN before trying to unlock the app.",
    "invalid_access_token": "The access token is invalid or expired.",
    "validation_error": "The request contains invalid fields.",
    "email_already_registered": "This email already has an account.",
    "invalid_verification_token": "The verification link is invalid or expired.",
    "invalid_credentials": "The email or password is incorrect.",
    "email_not_verified": "Verify your email before continuing.",
    "pending_approval": "Your account is pending admin approval.",
    "rejected": "Your operator registration was rejected.",
    "invalid_admin_token": "A valid administrator session is required.",
    "operator_not_found": "The operator account was not found.",
    "invalid_approval_transition": "The account cannot be updated from its current approval state.",
    "notification_unavailable": "Notification delivery is temporarily unavailable.",
    "invalid_operator_token": "A valid HTO operator session is required.",
    "csv_required": "Upload a CSV file.",
    "malformed_csv": "The CSV file could not be parsed.",
    "missing_required_columns": "The CSV must include first_name, last_name, and phone_number.",
    "row_limit_exceeded": "A manifest can contain at most 500 rows.",
    "manifest_not_found": "The manifest was not found.",
    "manifest_already_confirmed": "This manifest has already been confirmed.",
    "no_valid_rows": "The manifest has no valid rows to confirm.",
    "manifest_not_confirmed": "Confirm the manifest before placing orders.",
    "pricing_tier_not_found": "The selected pricing tier is unavailable.",
    "pricing_unavailable": "Current package pricing is unavailable.",
    "invalid_pilgrim_selection": "Select valid pilgrims from this manifest.",
    "pilgrims_already_grouped": "One or more pilgrims already belong to a family group.",
    "family_group_not_found": "The family group was not found.",
    "invalid_family_group_size": "The family group size is outside the tier limits.",
    "family_group_required": "Select one complete Family group for this tier.",
    "complete_family_group_required": "Every member of the Family group must be selected.",
    "individual_pilgrims_required": "Grouped pilgrims require the Family tier.",
    "pilgrims_already_ordered": "One or more pilgrims are already included in an order.",
    "manifest_order_not_found": "The manifest order was not found.",
    "invoice_unavailable": "Invoice generation is temporarily unavailable.",
    "invoice_email_unavailable": "The order was saved, but invoice email delivery is unavailable.",
    "invalid_payment_transition": "This order cannot be confirmed from its current state.",
    "provisioning_unavailable": "Payment was recorded, but provisioning could not be queued.",
    "payment_not_confirmed": "Payment must be confirmed before provisioning.",
    "activation_code_unavailable": "An activation code could not be generated.",
    "activation_delivery_incomplete": "One or more activation links could not be delivered.",
    "family_contact_exists": "A family contact already exists. Update it instead.",
    "family_contact_not_found": "No family contact has been nominated.",
    "family_contact_notification_unavailable": "The nomination was saved, but WhatsApp is temporarily unavailable.",
    "activation_code_invalid": "This activation code is invalid.",
    "activation_code_already_used": "This activation code has already been used.",
    "activation_code_expired": "This activation code has expired.",
    "activation_code_phone_mismatch": "This activation code was issued to a different phone number.",
    "invalid_group_size": "Choose a valid group size for this package.",
    "payment_unavailable": "Both payment services are unavailable. Please try again.",
    "invalid_processor": "The payment processor is not supported.",
    "destination_geofence_not_configured": "Arrival alerts are not configured for this destination.",
    "cli_not_verified": "Verify your Nigerian number before making PSTN calls.",
    "pstn_balance_exhausted": "No PSTN minutes remain on your package.",
    "voice_unavailable": "Calling is temporarily unavailable.",
    "invalid_phone_number": "Enter a valid Nigerian mobile number.",
    "phone_verification_unavailable": "Phone verification is temporarily unavailable.",
    "cli_verification_rate_limited": "Too many verification attempts. Try again later.",
    "caller_identity_not_found": "Verification not found.",
    "invalid_state": "This action is not valid for the current step.",
    "verification_code_invalid": "That code did not match. Try again.",
    "number_already_verified_elsewhere": "This number is already verified on another account.",
    "no_active_caller_id": "No verified caller ID to revoke.",
    "sos_id_conflict": "This SOS identifier is already in use.",
    "sos_not_found": "The SOS alert was not found.",
    "sos_already_resolved": "This SOS alert has already been resolved.",
    "sos_already_cancelled": "This SOS alert has already been cancelled.",
    "push_subscription_failed": "Browser alert subscription is temporarily unavailable.",
    "otp_sent": "OTP sent",
    "pin_set": "PIN set",
    "verification_email_sent": "Verification email sent",
    "email_verified": "Email verified, pending admin approval",
}

_API_FR = {
    "feature_retired": "Cette fonctionnalité ne fait plus partie de DamDam. Veuillez mettre à jour l’application vers la dernière version.",
    "checkin_rate_limited": "Vous pouvez signaler votre sécurité une fois toutes les 15 minutes.",
    "checkin_id_conflict": "Cet identifiant de pointage est déjà utilisé.",
    "invalid_webhook_signature": "La signature du webhook n’est pas valide.",
    "invalid_webhook_payload": "Le contenu du webhook n’est pas valide.",
    "aggregator_unavailable": "L’émission de l’eSIM est en file d’attente et sera relancée automatiquement.",
    "package_not_found": "La formule est introuvable.",
    "package_not_active": "La formule n’est pas encore active.",
    "esim_profile_not_found": "Le profil eSIM n’a pas encore été émis.",
    "invalid_otp": "Le code de vérification est incorrect.",
    "otp_expired": "Le code de vérification a expiré.",
    "rate_limited": "Veuillez patienter avant de demander un nouveau code.",
    "locked": "Trop de tentatives. Veuillez patienter avant de réessayer.",
    "account_exists": "Ce numéro possède déjà un compte. Veuillez vous connecter.",
    "account_not_found": "Aucun compte ne correspond à ce numéro de téléphone.",
    "otp_unavailable": "La vérification est temporairement indisponible.",
    "invalid_refresh_token": "Le jeton d’actualisation n’est pas valide ou a expiré.",
    "pin_too_weak": "Choisissez un code PIN à 4 chiffres ni répétés ni consécutifs.",
    "invalid_pin": "Le code PIN est incorrect.",
    "pin_not_set": "Définissez un code PIN avant de déverrouiller l’application.",
    "invalid_access_token": "Le jeton d’accès n’est pas valide ou a expiré.",
    "validation_error": "La requête contient des champs non valides.",
    "email_already_registered": "Cette adresse e-mail possède déjà un compte.",
    "invalid_verification_token": "Le lien de vérification n’est pas valide ou a expiré.",
    "invalid_credentials": "L’adresse e-mail ou le mot de passe est incorrect.",
    "email_not_verified": "Vérifiez votre adresse e-mail avant de continuer.",
    "pending_approval": "Votre compte attend l’approbation d’un administrateur.",
    "rejected": "Votre inscription d’opérateur a été refusée.",
    "invalid_admin_token": "Une session administrateur valide est requise.",
    "operator_not_found": "Le compte opérateur est introuvable.",
    "invalid_approval_transition": "Le compte ne peut pas être modifié depuis son état d’approbation actuel.",
    "notification_unavailable": "L’envoi des notifications est temporairement indisponible.",
    "invalid_operator_token": "Une session opérateur HTO valide est requise.",
    "csv_required": "Téléversez un fichier CSV.",
    "malformed_csv": "Le fichier CSV n’a pas pu être analysé.",
    "missing_required_columns": "Le CSV doit contenir first_name, last_name et phone_number.",
    "row_limit_exceeded": "Un manifeste peut contenir au maximum 500 lignes.",
    "manifest_not_found": "Le manifeste est introuvable.",
    "manifest_already_confirmed": "Ce manifeste a déjà été confirmé.",
    "no_valid_rows": "Le manifeste ne contient aucune ligne valide à confirmer.",
    "manifest_not_confirmed": "Confirmez le manifeste avant de passer des commandes.",
    "pricing_tier_not_found": "La formule tarifaire sélectionnée est indisponible.",
    "pricing_unavailable": "Les tarifs actuels des formules sont indisponibles.",
    "invalid_pilgrim_selection": "Sélectionnez des pèlerins valides de ce manifeste.",
    "pilgrims_already_grouped": "Un ou plusieurs pèlerins appartiennent déjà à un groupe familial.",
    "family_group_not_found": "Le groupe familial est introuvable.",
    "invalid_family_group_size": "La taille du groupe familial ne respecte pas les limites de la formule.",
    "family_group_required": "Sélectionnez un groupe Famille complet pour cette formule.",
    "complete_family_group_required": "Tous les membres du groupe Famille doivent être sélectionnés.",
    "individual_pilgrims_required": "Les pèlerins regroupés nécessitent la formule Famille.",
    "pilgrims_already_ordered": "Un ou plusieurs pèlerins figurent déjà dans une commande.",
    "manifest_order_not_found": "La commande du manifeste est introuvable.",
    "invoice_unavailable": "La génération de facture est temporairement indisponible.",
    "invoice_email_unavailable": "La commande a été enregistrée, mais l’envoi de la facture par e-mail est indisponible.",
    "invalid_payment_transition": "Cette commande ne peut pas être confirmée depuis son état actuel.",
    "provisioning_unavailable": "Le paiement a été enregistré, mais le provisionnement n’a pas pu être mis en file d’attente.",
    "payment_not_confirmed": "Le paiement doit être confirmé avant le provisionnement.",
    "activation_code_unavailable": "Aucun code d’activation n’a pu être généré.",
    "activation_delivery_incomplete": "Un ou plusieurs liens d’activation n’ont pas pu être envoyés.",
    "family_contact_exists": "Un contact familial existe déjà. Modifiez-le plutôt.",
    "family_contact_not_found": "Aucun contact familial n’a été désigné.",
    "family_contact_notification_unavailable": "La désignation a été enregistrée, mais WhatsApp est temporairement indisponible.",
    "activation_code_invalid": "Ce code d’activation n’est pas valide.",
    "activation_code_already_used": "Ce code d’activation a déjà été utilisé.",
    "activation_code_expired": "Ce code d’activation a expiré.",
    "activation_code_phone_mismatch": "Ce code d’activation a été émis pour un autre numéro de téléphone.",
    "invalid_group_size": "Choisissez une taille de groupe valide pour cette formule.",
    "payment_unavailable": "Les deux services de paiement sont indisponibles. Veuillez réessayer.",
    "invalid_processor": "Le prestataire de paiement n’est pas pris en charge.",
    "destination_geofence_not_configured": "Les alertes d’arrivée ne sont pas configurées pour cette destination.",
    "cli_not_verified": "Vérifiez votre numéro nigérian avant de passer des appels téléphoniques.",
    "pstn_balance_exhausted": "Votre formule ne contient plus de minutes téléphoniques.",
    "voice_unavailable": "Les appels sont temporairement indisponibles.",
    "invalid_phone_number": "Saisissez un numéro mobile nigérian valide.",
    "phone_verification_unavailable": "La vérification du téléphone est temporairement indisponible.",
    "cli_verification_rate_limited": "Trop de tentatives de vérification. Réessayez plus tard.",
    "caller_identity_not_found": "Vérification introuvable.",
    "invalid_state": "Cette action n’est pas valide à l’étape actuelle.",
    "verification_code_invalid": "Ce code ne correspond pas. Réessayez.",
    "number_already_verified_elsewhere": "Ce numéro est déjà vérifié sur un autre compte.",
    "no_active_caller_id": "Aucune identité d’appelant vérifiée à révoquer.",
    "sos_id_conflict": "Cet identifiant SOS est déjà utilisé.",
    "sos_not_found": "L’alerte SOS est introuvable.",
    "sos_already_resolved": "Cette alerte SOS a déjà été résolue.",
    "sos_already_cancelled": "Cette alerte SOS a déjà été annulée.",
    "push_subscription_failed": "L’abonnement aux alertes du navigateur est temporairement indisponible.",
    "otp_sent": "Code de vérification envoyé",
    "pin_set": "Code PIN défini",
    "verification_email_sent": "E-mail de vérification envoyé",
    "email_verified": "E-mail vérifié, en attente d’approbation",
}

_VALIDATOR_FR = {
    "Enter an 11-digit Nigerian mobile number": "Saisissez un numéro mobile nigérian à 11 chiffres",
    "OTP must contain exactly 6 digits": "Le code de vérification doit contenir exactement 6 chiffres",
    "Choose a non-repeated, non-sequential 4-digit PIN": "Choisissez un code PIN à 4 chiffres ni répétés ni consécutifs",
    "Field cannot be blank": "Ce champ ne peut pas être vide",
    "Enter a valid email address": "Saisissez une adresse e-mail valide",
    "At least one field is required": "Au moins un champ est requis",
    "latitude and longitude must be provided together": "La latitude et la longitude doivent être fournies ensemble",
    "activation_code is required": "Le code d’activation est requis",
    "Enter a Nigerian number in 0XXXXXXXXXX or +234 format": "Saisissez un numéro nigérian au format 0XXXXXXXXXX ou +234",
}


def normalize_locale(value: object) -> str:
    raw = getattr(value, "value", value)
    if isinstance(raw, str) and raw.strip().lower().startswith("fr"):
        return FR
    return EN


def request_locale(request: Request) -> str:
    headers = getattr(request, "headers", {})
    return normalize_locale(headers.get("accept-language", EN))


def translate(key: str, locale: object = EN, **values: object) -> str:
    catalog = _API_FR if normalize_locale(locale) == FR else _API_EN
    text = catalog.get(key) or _API_EN.get(key) or key
    return text.format(**values) if values else text


def api_message(request: Request, code: str) -> str:
    return translate(code, request_locale(request))


def localize_validation_errors(
    errors: Sequence[dict[str, Any]], locale: object
) -> list[dict[str, Any]]:
    localized = list(deepcopy(errors))
    if normalize_locale(locale) != FR:
        return localized
    for error in localized:
        message = error.get("msg")
        if isinstance(message, str):
            bare = message.removeprefix("Value error, ")
            translated = _VALIDATOR_FR.get(bare)
            if translated:
                error["msg"] = (
                    f"Erreur de valeur, {translated}"
                    if message.startswith("Value error, ")
                    else translated
                )
    return localized
