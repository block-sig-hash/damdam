# ruff: noqa: E501

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from fastapi import Request

EN = "en"
FR = "fr"

_API_EN = {
    # Outbound internet calling (US-45, chunk V02). Every refusal is phrased
    # for the person holding the phone, not for the engineer reading the log:
    # it says what happened and what they can do, and never names a provider,
    # a blocker or an internal rule.
    "calling_route_disabled": "Calling over the internet is not available yet.",
    "destination_not_e164": "Enter the full number including its country code, starting with +.",
    "destination_emergency_or_special": "Emergency and service numbers cannot be called from DamDam. Use your phone's own dialler.",
    "destination_premium": "Premium-rate numbers cannot be called from DamDam.",
    "destination_country_not_supported": "We do not offer calls to that country yet.",
    "destination_country_unknown": "We could not recognise that country code.",
    "rate_unavailable": "We have no published call rate for that destination yet.",
    "rate_unusable": "We cannot price a call to that destination yet.",
    "invalid_duration": "Choose a call length of at least one second.",
    "attempt_not_found": "We could not find that call.",
    "attempt_expired": "That call authorization has expired. Try calling again.",
    "attempt_not_startable": "That call has already finished.",
    "idempotency_conflict": "That request key was already used for different work.",
    "insufficient_funds": "You do not have enough credit for this call.",
    "reservation_failed": "We could not hold credit for this call. Please try again.",
    "device_not_authorized": "This device is not signed in for calling. Sign in again.",
    "entitlement_not_available": "That calling allowance is not available on your account.",
    "device_id_required": "This device could not be identified.",
    "session_rate_limited": "Too many calling sessions from this device. Wait a moment.",
    "session_outcome_unknown": "We could not confirm your calling session. Wait a moment before trying again.",
    "destination_not_answered": "The call has not been answered yet.",
    "webhook_verification_unconfigured": "This request could not be verified.",
    "capability_not_available": "Calling is not available on this account yet.",
    "telnyx_not_configured": "Calling is not available yet.",
    "provider_rejected": "The call could not be connected.",
    "invalid_provider_response": "The call could not be connected.",
    "credential_expiry_unknown": "Calling could not be set up on this device.",
    "not_a_member": "You do not have access to this organization.",
    "line_not_found": "We could not find that line on your account.",
    # Account, receipts and support (US-38, chunk 21). Every one of these is
    # said to a customer who is already having a bad day, so none of them
    # blames them and none of them says "invalid".
    "session_not_found": "That device is not signed in to your account.",
    "receipt_not_found": "We could not find that receipt on your account.",
    "account_deletion_blocked": "Resolve the items shown in Account before deleting your account.",
    "entitlement_not_found": "We could not find that line on your account.",
    "support_reference_unavailable": (
        "We could not start your request just now. Please try again."
    ),
    "profile_not_issued": "Your eSIM profile has not been issued yet. We will have it shortly.",
    "installation_material_unavailable": "eSIM installation is not available on this service yet. Nothing is wrong with your line.",
    "installation_reporting_unavailable": "We could not record your installation just now. Try again shortly.",
    "grant_not_redeemable": "That eSIM link is no longer usable. Open your line again to get a new one.",
    "market_unavailable": "This country and currency are not on sale yet.",
    "product_unavailable": "That plan is no longer available.",
    "quote_not_found": "We could not find that price. Please start again.",
    "quote_expired": "That price has expired. Get a fresh one to continue.",
    "quote_already_redeemed": "That price has already been used. Get a fresh one.",
    "quote_void": "That price is no longer valid. Get a fresh one.",
    "quote_tampered": "That price could not be verified. Please start again.",
    "quote_not_yours": "That price was prepared for a different recipient.",
    "quote_empty": "Choose a plan before continuing.",
    "empty_quote": "Choose a plan before continuing.",
    "invalid_quantity": "Choose at least one of each plan.",
    "currency_unsupported": "We cannot take payment in that currency.",
    "no_verified_supplier": "We have no verified supplier for that plan yet.",
    "supplier_capability_mismatch": "No supplier can deliver everything that plan includes.",
    "coverage_unavailable": "We have no verified network coverage for that plan yet.",
    "device_rule_missing": "That plan has no device requirements recorded yet.",
    "device_not_checked": "This plan needs an eSIM. Check your device before continuing.",
    "device_not_esim_capable": "This phone cannot take an eSIM, so this plan will not work on it.",
    "device_locked": "This plan needs an unlocked phone.",
    "price_unavailable": "That plan has no price in this currency.",
    "tariff_unavailable": "That plan includes calls but has no published call rates yet.",
    "market_not_verified": "That market has not been verified for sale.",
    "order_not_found": "We could not find that order.",
    # Bulk provisioning (US-40, chunk 23). Said to an administrator mid-way
    # through buying for fifty people, so each one says what to do next.
    "job_not_found": "We could not find that bulk order on your account.",
    # Enterprise offboarding (US-40, chunk 24).
    "offboarding_not_found": "We could not find that offboarding record.",
    "item_not_found": "We could not find that line in this bulk order.",
    "market_has_no_seller": (
        "We cannot sell in that market yet. Please contact support."
    ),
    "item_already_provisioned": (
        "That line is already active. Cancelling it is a refund request."
    ),
    "item_outcome_unknown": (
        "We are still confirming that line with our supplier. Please try again "
        "shortly."
    ),
    "item_not_awaiting_supplier": (
        "That line is not waiting for a supplier outcome."
    ),
    "recipient_archived": "This recipient has left the organization.",
    "line_not_ready": "That line is not ready to be handed over yet.",
    "activation_request_exists": "That person already has an invitation waiting.",
    "activation_request_spent": "That invitation has already been used.",
    "activation_request_revoked": "That invitation was withdrawn.",
    "activation_request_expired": "That invitation has expired.",
    "activation_request_not_found": "We could not find that invitation.",
    "job_not_fundable": "That bulk order cannot be funded in its current state.",
    "job_not_provisionable": (
        "That bulk order cannot be started in its current state."
    ),
    # Chunk 25 (US-41). These are read by internal operators rather than
    # customers, so they name the missing step instead of apologising for it:
    # the reader is the person who can go and do it.
    "reconciliation_required": (
        "Reconcile this attempt against the supplier's original reference "
        "before recording an outcome. Resolving it without asking is how a "
        "second purchase gets made."
    ),
    "provider_reference_required": (
        "Record the supplier's own reference for the success you are "
        "confirming."
    ),
    "supplier_success_not_adopted": (
        "That supplier reference is not attached to a local line yet. Reconcile "
        "and adopt the service before marking it provisioned."
    ),
    "supplier_failure_has_adopted_service": (
        "A local carrier line already proves this service was adopted. Resolve "
        "that contradiction before marking the purchase failed."
    ),
    "attempt_already_settled": (
        "That supplier attempt already has a definitive outcome."
    ),
    "cross_currency_compensation": (
        "A compensating entry moves one currency. Converting here would invent "
        "a rate nobody agreed."
    ),
    "one_identifier_required": (
        "Look a line up by exactly one of its id, its ICCID or its number."
    ),
    "non_positive_amount": "A compensating entry needs a positive amount.",
    "supplier_attempt_not_found": "We could not find that supplier attempt.",
    "exception_not_found": "We could not find that exception item.",
    "exception_subject_mismatch": (
        "That exception belongs to different work and cannot be closed by this action."
    ),
    "exception_already_resolved": "That exception has already been resolved.",
    "exception_kind_mismatch": "That exception cannot be resolved by this action.",
    "exception_requires_resolution": (
        "That exception carries money or service liability and cannot be dismissed."
    ),
    "bank_receipt_not_found": "We could not find that bank receipt.",
    "bank_receipt_not_unmatched": "That bank receipt has already been matched.",
    "invalid_customer_account": "Choose a customer service-credit account.",
    "call_charge_not_found": "We could not find that call charge.",
    "call_attempt_not_found": "We could not find the call behind that charge.",
    "ledger_account_not_found": "We could not find that ledger account.",
    "merchant_not_found": "No payment account is set up for this seller.",
    "live_collection_disabled": "We cannot take payments yet. Nothing has been charged.",
    "no_merchant_account": "No payment account is set up for this currency.",
    "payment_method_not_supported": "That payment method is not available for this order.",
    "ambiguous_merchant_route": "Payment is not available while the seller's payment route is being corrected.",
    "attempt_in_progress": "We are still confirming the existing payment. Do not pay again.",
    "wrong_processor": "The selected payment processor cannot collect this order.",
    "currency_mismatch": "That payment account does not take this currency.",
    "already_paid": "This order is already paid.",
    "intent_not_found": "We could not find that payment.",
    "permission_denied": "Your role does not allow this action.",
    "membership_not_found": "That person is not a member of this organization.",
    "role_change_forbidden": "You cannot grant or change a role at or above your own.",
    "cannot_modify_own_membership": "You cannot change your own membership.",
    "last_owner": "An organization must keep at least one owner.",
    "already_a_member": "That person is already a member of this organization.",
    "organization_not_selected": "Choose which organization you are acting in.",
    "shared_credential_forbidden": "This action requires an individual account, not the shared organization login.",
    "invitation_invalid": "That invitation is no longer valid.",
    "invitation_expired": "That invitation has expired. Ask for a new one.",
    "invitation_not_found": "The invitation was not found.",
    "invitation_already_pending": "An invitation to that address is already outstanding.",
    "invitation_recipient_mismatch": "That invitation was sent to a different address.",
    "mfa_not_enrolled": "Set up two-factor authentication before continuing.",
    "mfa_already_enrolled": "Two-factor authentication is already active. Disable it with your current authenticator or a recovery code before replacing it.",
    "mfa_enrollment_required": "This action requires two-factor authentication. Set it up to continue.",
    "mfa_required": "Confirm your authenticator code to continue.",
    "mfa_code_invalid": "That authenticator code is incorrect.",
    "mfa_code_replayed": "That code has already been used. Wait for the next one.",
    "mfa_locked": "Too many incorrect codes. Please wait before trying again.",
    "identity_sent": "If that address can receive it, we have sent a message with the next step.",
    "identity_verified": "Your email address is confirmed.",
    "identity_token_invalid": "That link is no longer valid. Please request a new one.",
    "identity_token_expired": "That link has expired. Please request a new one.",
    "identifier_already_verified": "That address is already confirmed on another account.",
    "identity_send_throttled": "Please wait before requesting another message.",
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
    # Appels sortants par internet (US-45, chunk V02).
    "calling_route_disabled": "Les appels par internet ne sont pas encore disponibles.",
    "destination_not_e164": "Saisissez le numéro complet avec son indicatif pays, en commençant par +.",
    "destination_emergency_or_special": "Les numéros d'urgence et de service ne peuvent pas être appelés depuis DamDam. Utilisez le téléphone de votre appareil.",
    "destination_premium": "Les numéros surtaxés ne peuvent pas être appelés depuis DamDam.",
    "destination_country_not_supported": "Nous ne proposons pas encore d'appels vers ce pays.",
    "destination_country_unknown": "Nous n'avons pas reconnu cet indicatif pays.",
    "rate_unavailable": "Aucun tarif publié pour cette destination pour le moment.",
    "rate_unusable": "Nous ne pouvons pas encore tarifer un appel vers cette destination.",
    "invalid_duration": "Choisissez une durée d'appel d'au moins une seconde.",
    "attempt_not_found": "Nous n'avons pas trouvé cet appel.",
    "attempt_expired": "Cette autorisation d'appel a expiré. Rappelez pour continuer.",
    "attempt_not_startable": "Cet appel est déjà terminé.",
    "idempotency_conflict": (
        "Cette clé de requête a déjà servi pour une autre opération."
    ),
    "insufficient_funds": "Votre crédit est insuffisant pour cet appel.",
    "reservation_failed": "Nous n'avons pas pu réserver le crédit de cet appel. Réessayez.",
    "device_not_authorized": "Cet appareil n'est pas connecté pour les appels. Reconnectez-vous.",
    "entitlement_not_available": "Ce forfait d'appels n'est pas disponible sur votre compte.",
    "device_id_required": "Cet appareil n'a pas pu être identifié.",
    "session_rate_limited": "Trop de sessions d'appel depuis cet appareil. Patientez un instant.",
    "session_outcome_unknown": "Nous n'avons pas pu confirmer votre session d'appel. Patientez avant de réessayer.",
    "destination_not_answered": "L'appel n'a pas encore été décroché.",
    "webhook_verification_unconfigured": "Cette requête n'a pas pu être vérifiée.",
    "capability_not_available": "Les appels ne sont pas encore disponibles sur ce compte.",
    "telnyx_not_configured": "Les appels ne sont pas encore disponibles.",
    "provider_rejected": "L'appel n'a pas pu être établi.",
    "invalid_provider_response": "L'appel n'a pas pu être établi.",
    "credential_expiry_unknown": "Les appels n'ont pas pu être configurés sur cet appareil.",
    "not_a_member": "Vous n'avez pas accès à cette organisation.",
    "permission_denied": "Votre rôle ne permet pas cette action.",
    "membership_not_found": "Cette personne n'est pas membre de cette organisation.",
    "role_change_forbidden": "Vous ne pouvez pas attribuer ni modifier un rôle égal ou supérieur au vôtre.",
    "cannot_modify_own_membership": "Vous ne pouvez pas modifier votre propre adhésion.",
    "last_owner": "Une organisation doit conserver au moins un propriétaire.",
    "already_a_member": "Cette personne est déjà membre de cette organisation.",
    "organization_not_selected": "Choisissez l'organisation dans laquelle vous agissez.",
    "shared_credential_forbidden": "Cette action exige un compte individuel, et non l'identifiant partagé de l'organisation.",
    "invitation_invalid": "Cette invitation n'est plus valide.",
    "line_not_found": "Nous n'avons pas trouvé cette ligne sur votre compte.",
    "session_not_found": "Cet appareil n'est pas connecté à votre compte.",
    "receipt_not_found": "Nous n'avons pas trouvé ce reçu sur votre compte.",
    "account_deletion_blocked": "Résolvez les éléments affichés dans Compte avant de supprimer votre compte.",
    "entitlement_not_found": (
        "Nous n'avons pas trouvé cette ligne sur votre compte."
    ),
    "support_reference_unavailable": (
        "Nous n'avons pas pu ouvrir votre demande. Veuillez réessayer."
    ),
    "profile_not_issued": "Votre profil eSIM n'a pas encore été émis. Nous l'aurons sous peu.",
    "installation_material_unavailable": "L'installation eSIM n'est pas encore disponible sur ce service. Votre ligne n'a aucun problème.",
    "installation_reporting_unavailable": "Nous n'avons pas pu enregistrer votre installation. Réessayez sous peu.",
    "grant_not_redeemable": "Ce lien eSIM n'est plus utilisable. Rouvrez votre ligne pour en obtenir un nouveau.",
    "market_unavailable": "Ce pays et cette devise ne sont pas encore en vente.",
    "product_unavailable": "Ce forfait n'est plus disponible.",
    "quote_not_found": "Nous n'avons pas trouvé ce prix. Veuillez recommencer.",
    "quote_expired": "Ce prix a expiré. Obtenez-en un nouveau pour continuer.",
    "quote_already_redeemed": "Ce prix a déjà été utilisé. Obtenez-en un nouveau.",
    "quote_void": "Ce prix n'est plus valide. Obtenez-en un nouveau.",
    "quote_tampered": "Ce prix n'a pas pu être vérifié. Veuillez recommencer.",
    "quote_not_yours": "Ce prix a été préparé pour un autre destinataire.",
    "quote_empty": "Choisissez un forfait avant de continuer.",
    "empty_quote": "Choisissez un forfait avant de continuer.",
    "invalid_quantity": "Choisissez au moins un exemplaire de chaque forfait.",
    "currency_unsupported": "Nous ne pouvons pas accepter de paiement dans cette devise.",
    "no_verified_supplier": "Nous n'avons pas encore de fournisseur vérifié pour ce forfait.",
    "supplier_capability_mismatch": "Aucun fournisseur ne peut livrer tout ce que ce forfait comprend.",
    "coverage_unavailable": "Nous n'avons pas encore de couverture réseau vérifiée pour ce forfait.",
    "device_rule_missing": "Aucune exigence d'appareil n'est encore enregistrée pour ce forfait.",
    "device_not_checked": "Ce forfait nécessite une eSIM. Vérifiez votre appareil avant de continuer.",
    "device_not_esim_capable": "Ce téléphone ne peut pas accepter d'eSIM ; ce forfait n'y fonctionnera pas.",
    "device_locked": "Ce forfait nécessite un téléphone déverrouillé.",
    "price_unavailable": "Ce forfait n'a pas de prix dans cette devise.",
    "tariff_unavailable": "Ce forfait comprend des appels mais aucun tarif publié.",
    "market_not_verified": "Ce marché n'a pas été vérifié pour la vente.",
    "order_not_found": "Nous n'avons pas trouvé cette commande.",
    "job_not_found": "Nous n'avons pas trouvé cette commande groupée.",
    "offboarding_not_found": "Nous n'avons pas trouvé cet enregistrement de départ.",
    "item_not_found": "Nous n'avons pas trouvé cette ligne dans cette commande.",
    "market_has_no_seller": (
        "Nous ne pouvons pas encore vendre sur ce marché. Contactez le support."
    ),
    "item_already_provisioned": (
        "Cette ligne est déjà active. L'annuler relève d'un remboursement."
    ),
    "item_outcome_unknown": (
        "Nous confirmons encore cette ligne auprès de notre fournisseur. "
        "Veuillez réessayer sous peu."
    ),
    "item_not_awaiting_supplier": (
        "Cette ligne n'attend pas de résultat du fournisseur."
    ),
    "recipient_archived": "Ce destinataire a quitté l'organisation.",
    "line_not_ready": "Cette ligne n'est pas encore prête à être transmise.",
    "activation_request_exists": (
        "Cette personne a déjà une invitation en attente."
    ),
    "activation_request_spent": "Cette invitation a déjà été utilisée.",
    "activation_request_revoked": "Cette invitation a été retirée.",
    "activation_request_expired": "Cette invitation a expiré.",
    "activation_request_not_found": "Nous n'avons pas trouvé cette invitation.",
    "job_not_fundable": (
        "Cette commande groupée ne peut pas être financée dans son état actuel."
    ),
    "job_not_provisionable": (
        "Cette commande groupée ne peut pas être lancée dans son état actuel."
    ),
    # Chunk 25 (US-41) — destiné aux opérateurs internes.
    "reconciliation_required": (
        "Rapprochez cette tentative de la référence d'origine du fournisseur "
        "avant d'enregistrer un résultat. La résoudre sans demander, c'est "
        "ainsi qu'un second achat est effectué."
    ),
    "provider_reference_required": (
        "Enregistrez la référence du fournisseur pour le succès que vous "
        "confirmez."
    ),
    "supplier_success_not_adopted": (
        "Cette référence fournisseur n'est pas encore liée à une ligne locale. "
        "Rapprochez et adoptez le service avant de le marquer provisionné."
    ),
    "supplier_failure_has_adopted_service": (
        "Une ligne opérateur locale prouve déjà que ce service a été adopté. "
        "Résolvez cette contradiction avant de marquer l'achat comme échoué."
    ),
    "attempt_already_settled": (
        "Cette tentative fournisseur a déjà un résultat définitif."
    ),
    "cross_currency_compensation": (
        "Une écriture de compensation ne déplace qu'une devise. Convertir ici "
        "inventerait un taux que personne n'a accepté."
    ),
    "one_identifier_required": (
        "Recherchez une ligne par exactement un identifiant : son id, son "
        "ICCID ou son numéro."
    ),
    "non_positive_amount": (
        "Une écriture de compensation exige un montant positif."
    ),
    "supplier_attempt_not_found": (
        "Nous n'avons pas trouvé cette tentative fournisseur."
    ),
    "exception_not_found": "Nous n'avons pas trouvé cet élément d'exception.",
    "exception_subject_mismatch": (
        "Cette exception concerne une autre opération et ne peut pas être "
        "fermée par cette action."
    ),
    "exception_already_resolved": "Cette exception a déjà été résolue.",
    "exception_kind_mismatch": (
        "Cette exception ne peut pas être résolue par cette action."
    ),
    "exception_requires_resolution": (
        "Cette exception engage des fonds ou un service et ne peut pas être classée."
    ),
    "bank_receipt_not_found": "Nous n'avons pas trouvé ce reçu bancaire.",
    "bank_receipt_not_unmatched": "Ce reçu bancaire a déjà été rapproché.",
    "invalid_customer_account": "Choisissez un compte de crédit de service client.",
    "call_charge_not_found": "Nous n'avons pas trouvé cette facturation d'appel.",
    "call_attempt_not_found": "Nous n'avons pas trouvé l'appel lié à cette facturation.",
    "ledger_account_not_found": "Nous n'avons pas trouvé ce compte du grand livre.",
    "merchant_not_found": "Aucun compte de paiement n'est configuré pour ce vendeur.",
    "live_collection_disabled": "Nous ne pouvons pas encore accepter de paiements. Rien n'a été débité.",
    "no_merchant_account": "Aucun compte de paiement n'est configuré pour cette devise.",
    "payment_method_not_supported": "Ce moyen de paiement n'est pas disponible pour cette commande.",
    "ambiguous_merchant_route": "Le paiement est indisponible pendant la correction du routage de paiement du vendeur.",
    "attempt_in_progress": "Nous confirmons encore le paiement existant. Ne payez pas une seconde fois.",
    "wrong_processor": "Le prestataire de paiement sélectionné ne peut pas encaisser cette commande.",
    "currency_mismatch": "Ce compte de paiement n'accepte pas cette devise.",
    "already_paid": "Cette commande est déjà payée.",
    "intent_not_found": "Nous n'avons pas trouvé ce paiement.",
    "invitation_expired": "Cette invitation a expiré. Demandez-en une nouvelle.",
    "invitation_not_found": "L'invitation est introuvable.",
    "invitation_already_pending": "Une invitation à cette adresse est déjà en attente.",
    "invitation_recipient_mismatch": "Cette invitation a été envoyée à une autre adresse.",
    "mfa_not_enrolled": "Configurez l'authentification à deux facteurs avant de continuer.",
    "mfa_already_enrolled": "L'authentification à deux facteurs est déjà active. Désactivez-la avec votre authentificateur actuel ou un code de récupération avant de la remplacer.",
    "mfa_enrollment_required": "Cette action exige l'authentification à deux facteurs. Configurez-la pour continuer.",
    "mfa_required": "Confirmez le code de votre application d'authentification pour continuer.",
    "mfa_code_invalid": "Ce code d'authentification est incorrect.",
    "mfa_code_replayed": "Ce code a déjà été utilisé. Attendez le suivant.",
    "mfa_locked": "Trop de codes incorrects. Veuillez patienter avant de réessayer.",
    "identity_sent": "Si cette adresse peut le recevoir, nous avons envoyé un message avec la suite.",
    "identity_verified": "Votre adresse e-mail est confirmée.",
    "identity_token_invalid": "Ce lien n’est plus valide. Veuillez en demander un nouveau.",
    "identity_token_expired": "Ce lien a expiré. Veuillez en demander un nouveau.",
    "identifier_already_verified": "Cette adresse est déjà confirmée sur un autre compte.",
    "identity_send_throttled": "Veuillez patienter avant de demander un autre message.",
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
