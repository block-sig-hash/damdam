from datetime import timedelta
from uuid import UUID, uuid4

import jwt
from fastapi.testclient import TestClient
from sqlmodel import select

from app.auth.models import (
    HTOApprovalStatus,
    Manifest,
    ManifestPilgrim,
    ManifestStatus,
    ManifestValidationStatus,
    Organization,
    OrganizationType,
)


def approved_organization(session_factory, email: str) -> Organization:
    organization = Organization(
        id=uuid4(),
        org_type=OrganizationType.HTO_OPERATOR,
        name="Barakah Hajj Services",
        primary_contact_name="Amina Yusuf",
        email=email,
        password_hash="not-used",
        phone_number="+2348012345678",
        nahcon_licence_number="NAHCON-123",
        email_verified=True,
        approval_status=HTOApprovalStatus.APPROVED,
    )
    with session_factory() as session:
        session.add(organization)
        session.commit()
        session.refresh(organization)
        session.expunge(organization)
    return organization


def access_token(settings, clock, organization_id: UUID) -> str:
    return jwt.encode(
        {
            "sub": str(organization_id),
            "aud": "hto_dashboard",
            "type": "access",
            "iat": clock(),
            "exp": clock() + timedelta(minutes=15),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def auth_headers(settings, clock, organization_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token(settings, clock, organization_id)}"}


def create_manifest(client: TestClient, headers: dict[str, str]) -> UUID:
    response = client.post(
        "/v1/hto/manifests", json={"name": "Flight NAF203"}, headers=headers
    )
    assert response.status_code == 201
    assert response.json()["status"] == "draft"
    return UUID(response.json()["manifest_id"])


def test_upload_previews_valid_invalid_and_duplicate_rows_then_confirms(
    api, session_factory, settings, clock
) -> None:
    """AC-05.2–05.7: validate independently and preview before confirmation."""
    organization = approved_organization(session_factory, "operator@example.com")
    headers = auth_headers(settings, clock, organization.id)
    client = TestClient(api)
    manifest_id = create_manifest(client, headers)
    csv_file = (
        "first_name,last_name,phone_number,passport_number,seat_number\n"
        "Aisha,Bello,08012345678,A1234567,14A\n"
        "Musa,Garba,12345,,\n"
        "Zainab,Bello,08012345678,,14B\n"
        "Hauwa,Sani,09012345678,P9876543,15A\n"
    )

    upload = client.post(
        f"/v1/hto/manifests/{manifest_id}/upload",
        headers=headers,
        files={"file": ("pilgrims.csv", csv_file, "text/csv")},
    )

    assert upload.status_code == 200
    body = upload.json()
    assert body["total_rows"] == 4
    assert body["valid_rows"] == 3
    assert body["invalid_rows"] == [
        {
            "row_number": 3,
            "reason": "phone_number must be an 11-digit Nigerian mobile number",
        }
    ]
    assert [row["row_number"] for row in body["preview"]] == [2, 4, 5]
    assert body["preview"][0]["phone_number"] == "+2348012345678"
    assert body["preview"][0]["passport_number"] == "A1234567"
    assert body["preview"][0]["validation_status"] == "duplicate_warning"
    assert body["preview"][1]["validation_status"] == "duplicate_warning"
    assert body["preview"][2]["validation_status"] == "valid"

    with session_factory() as session:
        staged = session.exec(
            select(ManifestPilgrim).where(
                ManifestPilgrim.manifest_id == manifest_id
            )
        ).all()
        assert len(staged) == 4
        assert any(
            pilgrim.validation_status == ManifestValidationStatus.INVALID
            for pilgrim in staged
        )

    confirmed = client.post(
        f"/v1/hto/manifests/{manifest_id}/confirm", headers=headers
    )
    assert confirmed.status_code == 200
    assert confirmed.json() == {"status": "validated", "pilgrim_count": 3}
    with session_factory() as session:
        manifest = session.get(Manifest, manifest_id)
        assert manifest is not None
        assert manifest.status == ManifestStatus.VALIDATED
        accepted = session.exec(
            select(ManifestPilgrim).where(
                ManifestPilgrim.manifest_id == manifest_id
            )
        ).all()
        assert len(accepted) == 3
        assert all(
            pilgrim.validation_status != ManifestValidationStatus.INVALID
            for pilgrim in accepted
        )


def test_upload_rejects_non_csv_missing_columns_and_more_than_500_rows(
    api, session_factory, settings, clock
) -> None:
    """AC-05.1/05.2: enforce CSV shape and the per-upload row cap."""
    organization = approved_organization(session_factory, "limits@example.com")
    headers = auth_headers(settings, clock, organization.id)
    client = TestClient(api)
    manifest_id = create_manifest(client, headers)

    non_csv = client.post(
        f"/v1/hto/manifests/{manifest_id}/upload",
        headers=headers,
        files={"file": ("pilgrims.txt", "not csv", "text/plain")},
    )
    assert non_csv.status_code == 415
    assert non_csv.json()["error"] == "csv_required"

    missing = client.post(
        f"/v1/hto/manifests/{manifest_id}/upload",
        headers=headers,
        files={"file": ("pilgrims.csv", "first_name,last_name\nA,B\n", "text/csv")},
    )
    assert missing.status_code == 400
    assert missing.json()["error"] == "missing_required_columns"

    oversized = "first_name,last_name,phone_number\n" + "".join(
        f"Pilgrim{index},Test,0801234{index:04d}\n" for index in range(501)
    )
    too_many = client.post(
        f"/v1/hto/manifests/{manifest_id}/upload",
        headers=headers,
        files={"file": ("pilgrims.csv", oversized, "text/csv")},
    )
    assert too_many.status_code == 400
    assert too_many.json()["error"] == "row_limit_exceeded"


def test_upload_rejects_malformed_csv_shapes(
    api, session_factory, settings, clock
) -> None:
    """Regression: encoding/structural CSV problems a semi-literate HTO
    operator (prd.md §3.2) is plausible to hit are rejected as
    malformed_csv rather than silently mis-parsed or crashing."""
    organization = approved_organization(session_factory, "malformed@example.com")
    headers = auth_headers(settings, clock, organization.id)
    client = TestClient(api)

    def upload(contents: str | bytes) -> object:
        manifest_id = create_manifest(client, headers)
        return client.post(
            f"/v1/hto/manifests/{manifest_id}/upload",
            headers=headers,
            files={"file": ("pilgrims.csv", contents, "text/csv")},
        )

    empty = upload("")
    assert empty.status_code == 400
    assert empty.json()["error"] == "malformed_csv"

    null_byte = upload(b"first_name,last_name,phone_number\n\x00,B,08012345678\n")
    assert null_byte.status_code == 400
    assert null_byte.json()["error"] == "malformed_csv"

    duplicate_headers = upload(
        "first_name,first_name,last_name,phone_number\nA,X,B,08012345678\n"
    )
    assert duplicate_headers.status_code == 400
    assert duplicate_headers.json()["error"] == "malformed_csv"

    ragged_row = upload(
        "first_name,last_name,phone_number\nA,B,08012345678,extra\n"
    )
    assert ragged_row.status_code == 200
    assert ragged_row.json()["invalid_rows"] == [
        {"row_number": 2, "reason": "Row has more values than the header"}
    ]

    over_length = upload(
        "first_name,last_name,phone_number,passport_number,seat_number\n"
        + f"{'A' * 101},B,08012345678,{'P' * 51},{'1' * 11}\n"
    )
    assert over_length.status_code == 200
    body = over_length.json()
    assert body["invalid_rows"] == [
        {
            "row_number": 2,
            "reason": (
                "first_name must be at most 100 characters; "
                "passport_number must be at most 50 characters; "
                "seat_number must be at most 10 characters"
            ),
        }
    ]


def test_manifest_endpoints_enforce_authentication_and_tenant_ownership(
    api, session_factory, settings, clock
) -> None:
    """Dashboard isolation: an HTO cannot read or mutate another tenant's batch."""
    owner = approved_organization(session_factory, "owner@example.com")
    attacker = approved_organization(session_factory, "attacker@example.com")
    owner_headers = auth_headers(settings, clock, owner.id)
    attacker_headers = auth_headers(settings, clock, attacker.id)
    client = TestClient(api)
    manifest_id = create_manifest(client, owner_headers)

    assert client.get("/v1/hto/manifests").status_code == 401
    listing = client.get("/v1/hto/manifests", headers=attacker_headers)
    assert listing.status_code == 200
    assert listing.json() == {"manifests": []}

    upload = client.post(
        f"/v1/hto/manifests/{manifest_id}/upload",
        headers=attacker_headers,
        files={
            "file": (
                "pilgrims.csv",
                "first_name,last_name,phone_number\nA,B,08012345678\n",
                "text/csv",
            )
        },
    )
    assert upload.status_code == 404
    assert upload.json()["error"] == "manifest_not_found"
    confirm = client.post(
        f"/v1/hto/manifests/{manifest_id}/confirm", headers=attacker_headers
    )
    assert confirm.status_code == 404
