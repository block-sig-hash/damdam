from fastapi.testclient import TestClient


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
