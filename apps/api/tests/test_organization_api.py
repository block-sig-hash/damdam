"""US-29 chunk 07D — the same rules, proved through the HTTP surface.

The service-level suites prove the rules. This one proves the *routes* apply
them, which is the failure AC-29.4 actually describes: a correct service that
one endpoint forgets to call.

Every organization-scoped route therefore gets a negative cross-tenant case
here -- a caller with a perfectly valid session for organization A, asking
about organization B by id, by path or by header.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.auth.models import (
    Locale,
    Organization,
    OrganizationType,
    Platform,
    User,
)
from app.identity.models import AccountIdentifier, IdentifierKind
from app.mfa.totp import generate
from app.organizations.models import OrganizationRole
from app.organizations.service import MembershipService

ACME_OWNER_EMAIL = "acme.owner@example.test"
OTHER_OWNER_EMAIL = "other.owner@example.test"
JOINER_EMAIL = "joiner@example.test"


@pytest.fixture
def client(api):
    return TestClient(api, raise_server_exceptions=False)


def _user(session: Session, label: str, email: str | None = None) -> UUID:
    user = User(
        phone_number=f"+23483{abs(hash(label)) % 10**8:08d}",
        first_name=label,
        platform=Platform.ANDROID,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    if email is not None:
        session.add(
            AccountIdentifier(
                user_id=user.id,
                kind=IdentifierKind.EMAIL,
                value=email.lower(),
                verified_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
                is_primary=True,
            )
        )
        session.commit()
    # The id, not the instance: these helpers are called inside short-lived
    # sessions and everything downstream re-reads the row it needs.
    return user.id


def _organization(session: Session, name: str) -> Organization:
    organization = Organization(
        org_type=OrganizationType.ENTERPRISE,
        name=name,
        primary_contact_name="Contact",
        email=f"{name.lower()}-{uuid4().hex[:8]}@example.test",
        password_hash="unused",
        phone_number="+2348000000000",
        locale=Locale.EN,
    )
    session.add(organization)
    session.commit()
    session.refresh(organization)
    return organization


def _token(api, user_id: UUID) -> str:
    """Mint a real access token through the app's own token service."""
    with api.state.session_factory() as session:
        pair = api.state.otp_service.tokens.issue(
            session, session.get(User, user_id), api.state.clock()
        )
        session.commit()
    return pair.access_token


def _auth(api, user_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(api, user_id)}"}


def _seed(api, session_factory, clock):
    """Two organizations, each with its own owner, plus a bystander."""
    memberships = MembershipService(clock=clock)
    with session_factory() as session:
        acme = _organization(session, "Acme")
        other = _organization(session, "Other")
        acme_owner = _user(session, "acme-owner", ACME_OWNER_EMAIL)
        other_owner = _user(session, "other-owner", OTHER_OWNER_EMAIL)
        bystander = _user(session, "bystander")
        memberships.seed_member(
            session, acme, session.get(User, acme_owner), OrganizationRole.OWNER
        )
        memberships.seed_member(
            session, other, session.get(User, other_owner), OrganizationRole.OWNER
        )
        session.commit()
        return {
            "acme": acme.id,
            "other": other.id,
            "acme_owner": acme_owner,
            "other_owner": other_owner,
            "bystander": bystander,
        }


def _enroll_and_step_up(api, client, user, organization_id, clock):
    headers = _auth(api, user)
    enrolled = client.post("/v1/auth/mfa/enroll", headers=headers)
    assert enrolled.status_code == 200
    secret = enrolled.json()["secret"]
    import base64

    padded = secret + "=" * (-len(secret) % 8)
    raw = base64.b32decode(padded)
    confirmed = client.post(
        "/v1/auth/mfa/enroll/confirm",
        headers=headers,
        json={"code": generate(raw, clock.value)},
    )
    assert confirmed.status_code == 200, confirmed.text
    clock.advance(seconds=30)
    stepped = client.post(
        f"/v1/organizations/{organization_id}/step-up",
        headers=headers,
        json={"code": generate(raw, clock.value)},
    )
    assert stepped.status_code == 200, stepped.text
    return headers, raw


# --- negative cross-tenant, one per organization-scoped route -------------


@pytest.mark.parametrize(
    ("method", "path_template"),
    [
        ("GET", "/v1/organizations/{other}/members"),
        ("GET", "/v1/organizations/{other}/invitations"),
        ("POST", "/v1/organizations/{other}/invitations"),
        ("PATCH", "/v1/organizations/{other}/members/{victim}"),
        ("DELETE", "/v1/organizations/{other}/members/{victim}"),
        ("DELETE", "/v1/organizations/{other}/invitations/{invitation}"),
        ("POST", "/v1/organizations/{other}/step-up"),
    ],
)
def test_a_valid_session_for_one_organization_cannot_reach_another(
    api, client, session_factory, clock, method, path_template
):
    seeded = _seed(api, session_factory, clock)
    path = path_template.format(
        other=seeded["other"],
        victim=seeded["other_owner"],
        invitation=uuid4(),
    )
    response = client.request(
        method,
        path,
        headers=_auth(api, seeded["acme_owner"]),
        json={"email": "x@example.test", "role": "member", "code": "123456"},
    )
    assert response.status_code == 403, (path, response.status_code, response.text)
    assert response.json()["error"] == "not_a_member"


def test_a_person_with_no_membership_anywhere_is_refused(
    api, client, session_factory, clock
):
    seeded = _seed(api, session_factory, clock)
    response = client.get(
        f"/v1/organizations/{seeded['acme']}/members",
        headers=_auth(api, seeded["bystander"]),
    )
    assert response.status_code == 403
    assert response.json()["error"] == "not_a_member"


def test_an_unauthenticated_caller_is_refused(api, client, session_factory, clock):
    """401, not 403: nothing was proved, so there is nothing to authorize."""
    seeded = _seed(api, session_factory, clock)
    response = client.get(f"/v1/organizations/{seeded['acme']}/members")
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_access_token"


def test_an_expired_session_is_reported_as_a_session_problem(
    api, client, session_factory, clock
):
    """Not as a cross-tenant refusal -- the client has to know to refresh."""
    seeded = _seed(api, session_factory, clock)
    headers = _auth(api, seeded["acme_owner"])
    clock.value += timedelta(days=1)

    response = client.get(
        f"/v1/organizations/{seeded['acme']}/members", headers=headers
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_access_token"


def test_an_auth_version_change_invalidates_organization_routes(
    api, client, session_factory, clock
):
    """Organization guards must enforce the same recovery boundary as auth."""
    seeded = _seed(api, session_factory, clock)
    headers = _auth(api, seeded["acme_owner"])
    with session_factory() as session:
        user = session.get(User, seeded["acme_owner"])
        assert user is not None
        user.auth_version += 1
        session.add(user)
        session.commit()

    response = client.get(
        f"/v1/organizations/{seeded['acme']}/members", headers=headers
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_access_token"


def test_the_organization_list_shows_only_the_callers_own(
    api, client, session_factory, clock
):
    seeded = _seed(api, session_factory, clock)
    response = client.get(
        "/v1/organizations", headers=_auth(api, seeded["acme_owner"])
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["organizations"]]
    assert ids == [str(seeded["acme"])]


def test_a_nonexistent_organization_is_indistinguishable_from_someone_elses(
    api, client, session_factory, clock
):
    """Otherwise the API confirms which organization ids exist."""
    seeded = _seed(api, session_factory, clock)
    headers = _auth(api, seeded["acme_owner"])
    missing = client.get(f"/v1/organizations/{uuid4()}/members", headers=headers)
    foreign = client.get(
        f"/v1/organizations/{seeded['other']}/members", headers=headers
    )
    assert missing.status_code == foreign.status_code == 403
    assert missing.json() == foreign.json()


# --- the step-up gate, through HTTP ---------------------------------------


def test_inviting_is_refused_until_the_second_factor_is_proved(
    api, client, session_factory, clock
):
    seeded = _seed(api, session_factory, clock)
    headers = _auth(api, seeded["acme_owner"])

    without_enrollment = client.post(
        f"/v1/organizations/{seeded['acme']}/invitations",
        headers=headers,
        json={"email": JOINER_EMAIL, "role": "member"},
    )
    assert without_enrollment.status_code == 403
    assert without_enrollment.json()["error"] == "mfa_enrollment_required"


def test_reading_the_member_list_never_asks_for_a_second_factor(
    api, client, session_factory, clock
):
    seeded = _seed(api, session_factory, clock)
    response = client.get(
        f"/v1/organizations/{seeded['acme']}/members",
        headers=_auth(api, seeded["acme_owner"]),
    )
    assert response.status_code == 200
    assert len(response.json()["members"]) == 1


def test_the_full_invitation_journey(api, client, session_factory, clock):
    """Enroll, step up, invite, accept -- and the joiner lands in one tenant."""
    seeded = _seed(api, session_factory, clock)
    headers, _ = _enroll_and_step_up(
        api, client, seeded["acme_owner"], seeded["acme"], clock
    )

    invited = client.post(
        f"/v1/organizations/{seeded['acme']}/invitations",
        headers=headers,
        json={"email": JOINER_EMAIL, "role": "billing"},
    )
    assert invited.status_code == 201, invited.text
    token = invited.json()["token"]

    with session_factory() as session:
        joiner = _user(session, "joiner", JOINER_EMAIL)
    joiner_headers = _auth(api, joiner)

    listed = client.get("/v1/invitations", headers=joiner_headers)
    assert listed.status_code == 200
    assert len(listed.json()["invitations"]) == 1

    accepted = client.post(
        "/v1/invitations/accept", headers=joiner_headers, json={"token": token}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["role"] == "billing"
    assert accepted.json()["organization_id"] == str(seeded["acme"])

    mine = client.get("/v1/organizations", headers=joiner_headers)
    assert [item["id"] for item in mine.json()["organizations"]] == [
        str(seeded["acme"])
    ]


def test_a_stranger_cannot_accept_someone_elses_invitation_token(
    api, client, session_factory, clock
):
    seeded = _seed(api, session_factory, clock)
    headers, _ = _enroll_and_step_up(
        api, client, seeded["acme_owner"], seeded["acme"], clock
    )
    invited = client.post(
        f"/v1/organizations/{seeded['acme']}/invitations",
        headers=headers,
        json={"email": JOINER_EMAIL, "role": "member"},
    )
    token = invited.json()["token"]

    with session_factory() as session:
        interceptor = _user(session, "interceptor", "interceptor@example.test")
    response = client.post(
        "/v1/invitations/accept",
        headers=_auth(api, interceptor),
        json={"token": token},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "invitation_recipient_mismatch"


def test_an_invitation_list_is_empty_for_an_account_with_no_verified_address(
    api, client, session_factory, clock
):
    seeded = _seed(api, session_factory, clock)
    headers, _ = _enroll_and_step_up(
        api, client, seeded["acme_owner"], seeded["acme"], clock
    )
    client.post(
        f"/v1/organizations/{seeded['acme']}/invitations",
        headers=headers,
        json={"email": JOINER_EMAIL, "role": "member"},
    )
    response = client.get("/v1/invitations", headers=_auth(api, seeded["bystander"]))
    assert response.json()["invitations"] == []


# --- the last owner, through HTTP -----------------------------------------


def test_the_last_owner_cannot_be_removed_through_the_api(
    api, client, session_factory, clock
):
    seeded = _seed(api, session_factory, clock)
    headers, _ = _enroll_and_step_up(
        api, client, seeded["acme_owner"], seeded["acme"], clock
    )
    response = client.delete(
        f"/v1/organizations/{seeded['acme']}/members/{seeded['acme_owner']}",
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"] == "cannot_modify_own_membership"


def test_an_expired_step_up_stops_authorizing(api, client, session_factory, clock):
    seeded = _seed(api, session_factory, clock)
    _enroll_and_step_up(
        api, client, seeded["acme_owner"], seeded["acme"], clock
    )
    clock.value += timedelta(minutes=16)
    # A fresh access token, so the only thing that has lapsed is the step-up.
    headers = _auth(api, seeded["acme_owner"])

    response = client.post(
        f"/v1/organizations/{seeded['acme']}/invitations",
        headers=headers,
        json={"email": JOINER_EMAIL, "role": "member"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "mfa_required"


def test_wrong_step_up_attempts_are_committed_and_lock_the_http_flow(
    api, client, session_factory, clock
):
    seeded = _seed(api, session_factory, clock)
    headers = _auth(api, seeded["acme_owner"])
    enrolled = client.post("/v1/auth/mfa/enroll", headers=headers)
    assert enrolled.status_code == 200

    import base64

    encoded = enrolled.json()["secret"]
    secret = base64.b32decode(encoded + "=" * (-len(encoded) % 8))
    confirmed = client.post(
        "/v1/auth/mfa/enroll/confirm",
        headers=headers,
        json={"code": generate(secret, clock.value)},
    )
    assert confirmed.status_code == 200
    clock.advance(seconds=30)

    for _ in range(api.state.mfa_service.ATTEMPT_LIMIT):
        rejected = client.post(
            f"/v1/organizations/{seeded['acme']}/step-up",
            headers=headers,
            json={"code": "000000"},
        )
        assert rejected.status_code == 400

    locked = client.post(
        f"/v1/organizations/{seeded['acme']}/step-up",
        headers=headers,
        json={"code": generate(secret, clock.value)},
    )
    assert locked.status_code == 423
    assert locked.json()["error"] == "mfa_locked"


def test_an_active_second_factor_cannot_be_replaced_by_a_bearer_token(
    api, client, session_factory, clock
):
    seeded = _seed(api, session_factory, clock)
    headers = _auth(api, seeded["acme_owner"])
    enrolled = client.post("/v1/auth/mfa/enroll", headers=headers)
    encoded = enrolled.json()["secret"]

    import base64

    secret = base64.b32decode(encoded + "=" * (-len(encoded) % 8))
    confirmed = client.post(
        "/v1/auth/mfa/enroll/confirm",
        headers=headers,
        json={"code": generate(secret, clock.value)},
    )
    assert confirmed.status_code == 200

    replacement = client.post("/v1/auth/mfa/enroll", headers=headers)
    assert replacement.status_code == 409
    assert replacement.json()["error"] == "mfa_already_enrolled"


def test_error_messages_are_localized(api, client, session_factory, clock):
    seeded = _seed(api, session_factory, clock)
    response = client.get(
        f"/v1/organizations/{seeded['other']}/members",
        headers={**_auth(api, seeded["acme_owner"]), "Accept-Language": "fr"},
    )
    assert response.status_code == 403
    assert "organisation" in response.json()["message"].lower()


# --- the legacy shared credential boundary ---------------------------------


def _shared_credential_token(api, organization_id) -> str:
    """A real operator session, minted the way the legacy login mints one."""
    from app.auth.models import HTOApprovalStatus, OrganizationType

    with api.state.session_factory() as session:
        organization = session.get(Organization, organization_id)
        organization.org_type = OrganizationType.HTO_OPERATOR
        organization.nahcon_licence_number = "NAHCON-TEST-1"
        organization.email_verified = True
        organization.approval_status = HTOApprovalStatus.APPROVED
        session.add(organization)
        session.commit()
        pair = api.state.hto_service._issue_tokens(session, organization)
    return pair.access_token


def test_the_shared_credential_still_opens_the_reporting_flow(
    api, client, session_factory, clock
):
    """Compatibility: the dashboard keeps working while it migrates."""
    seeded = _seed(api, session_factory, clock)
    token = _shared_credential_token(api, seeded["acme"])
    response = client.get(
        "/v1/hto/reports/provisioning.csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_the_shared_credential_cannot_manage_people(
    api, client, session_factory, clock
):
    """The replacement, made real before the dashboard has migrated.

    A password several people know cannot be attributed to one of them, cannot
    carry a second factor and cannot be revoked for one of them -- so it is
    refused for every privileged action, whatever the organization's plan says.
    """
    seeded = _seed(api, session_factory, clock)
    token = _shared_credential_token(api, seeded["acme"])
    headers = {"Authorization": f"Bearer {token}"}

    invited = client.post(
        f"/v1/organizations/{seeded['acme']}/invitations",
        headers=headers,
        json={"email": JOINER_EMAIL, "role": "member"},
    )
    assert invited.status_code == 403
    assert invited.json()["error"] == "shared_credential_forbidden"

    revoked = client.delete(
        f"/v1/organizations/{seeded['acme']}/members/{seeded['acme_owner']}",
        headers=headers,
    )
    assert revoked.status_code == 403
    assert revoked.json()["error"] == "shared_credential_forbidden"


def test_a_shared_credential_cannot_read_another_organization(
    api, client, session_factory, clock
):
    seeded = _seed(api, session_factory, clock)
    token = _shared_credential_token(api, seeded["acme"])
    response = client.get(
        f"/v1/organizations/{seeded['other']}/members",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "not_a_member"


def test_a_member_session_must_name_its_tenant_on_the_legacy_routes(
    api, client, session_factory, clock
):
    """No defaulting to "their only organization" -- that changes meaning the
    day they join a second one."""
    seeded = _seed(api, session_factory, clock)
    headers = _auth(api, seeded["acme_owner"])

    without_header = client.get("/v1/hto/manifests", headers=headers)
    assert without_header.status_code == 400
    assert without_header.json()["error"] == "organization_not_selected"

    with_header = client.get(
        "/v1/hto/manifests",
        headers={**headers, "X-Organization-Id": str(seeded["acme"])},
    )
    assert with_header.status_code == 200


def test_a_member_cannot_point_the_header_at_another_tenant(
    api, client, session_factory, clock
):
    seeded = _seed(api, session_factory, clock)
    response = client.get(
        "/v1/hto/manifests",
        headers={
            **_auth(api, seeded["acme_owner"]),
            "X-Organization-Id": str(seeded["other"]),
        },
    )
    assert response.status_code == 403
    assert response.json()["error"] == "not_a_member"


def test_a_plain_member_cannot_export_another_tenants_report(
    api, client, session_factory, clock
):
    """Object-level, not screen-level: the export is a route like any other."""
    seeded = _seed(api, session_factory, clock)
    with session_factory() as session:
        plain = _user(session, "plain-member")
        memberships = MembershipService(clock=clock)
        memberships.seed_member(
            session,
            session.get(Organization, seeded["acme"]),
            session.get(User, plain),
            OrganizationRole.MEMBER,
        )
        session.commit()

    own = client.get(
        "/v1/hto/reports/provisioning.csv",
        headers={**_auth(api, plain), "X-Organization-Id": str(seeded["acme"])},
    )
    assert own.status_code == 403
    assert own.json()["error"] == "permission_denied"

    foreign = client.get(
        "/v1/hto/reports/provisioning.csv",
        headers={**_auth(api, plain), "X-Organization-Id": str(seeded["other"])},
    )
    assert foreign.status_code == 403
    assert foreign.json()["error"] == "not_a_member"
