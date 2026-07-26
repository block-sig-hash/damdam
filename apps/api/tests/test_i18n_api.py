from fastapi.testclient import TestClient

from app.i18n import translate


def test_accept_language_localizes_stable_api_error(api) -> None:
    response = TestClient(api).post(
        "/v1/auth/otp/request",
        headers={"Accept-Language": "fr-SN,fr;q=0.9"},
        json={"phone_number": "not-a-number", "locale": "fr"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] == "validation_error"
    assert payload["message"] == "La requête contient des champs non valides."
    assert (
        "Saisissez un numéro mobile nigérian"
        in (payload["details"]["errors"][0]["msg"])
    )


def test_unsupported_accept_language_falls_back_to_english(api) -> None:
    response = TestClient(api).post(
        "/v1/auth/otp/request",
        headers={"Accept-Language": "ar-SA"},
        json={"phone_number": "not-a-number"},
    )

    assert response.status_code == 422
    assert response.json()["message"] == "The request contains invalid fields."


def test_caller_identity_errors_have_english_and_french_copy() -> None:
    expected = {
        "invalid_phone_number": "Saisissez un numéro mobile nigérian valide.",
        "phone_verification_unavailable": (
            "La vérification du téléphone est temporairement indisponible."
        ),
        "cli_verification_rate_limited": (
            "Trop de tentatives de vérification. Réessayez plus tard."
        ),
        "caller_identity_not_found": "Vérification introuvable.",
        "invalid_state": "Cette action n’est pas valide à l’étape actuelle.",
        "verification_code_invalid": "Ce code ne correspond pas. Réessayez.",
        "number_already_verified_elsewhere": (
            "Ce numéro est déjà vérifié sur un autre compte."
        ),
        "no_active_caller_id": "Aucune identité d’appelant vérifiée à révoquer.",
    }

    for code, french in expected.items():
        assert translate(code, "en") != code
        assert translate(code, "fr") == french
