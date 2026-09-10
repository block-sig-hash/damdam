"""The organization permission matrix (US-29, AC-29.3).

The matrix is *data*, declared once and read by the server on every request. It
is deliberately not expressed as `if role == "admin"` scattered through route
handlers: the failure mode this chunk exists to prevent is one endpoint whose
check drifted from the others, and a scattered rule cannot be reviewed for
completeness.

`permissions_for` raises for an unknown role rather than returning an empty set,
because a role added later without a matrix entry must fail loudly at import
time, not quietly authorize nothing (or, worse, be handled by some caller's
`.get(role, ALL)`).
"""

from enum import Enum

from app.organizations.models import OrganizationRole


class Permission(str, Enum):
    """What a membership may do. Named for the action, not for the screen."""

    ORG_READ = "org:read"
    ORG_UPDATE = "org:update"
    ORG_TRANSFER_OWNERSHIP = "org:transfer_ownership"

    MEMBER_READ = "member:read"
    MEMBER_INVITE = "member:invite"
    MEMBER_ROLE_CHANGE = "member:role_change"
    MEMBER_REVOKE = "member:revoke"

    BILLING_READ = "billing:read"
    BILLING_MANAGE = "billing:manage"

    ORDER_READ = "order:read"
    ORDER_PLACE = "order:place"

    PEOPLE_READ = "people:read"
    PEOPLE_MANAGE = "people:manage"

    REPORT_READ = "report:read"
    REPORT_EXPORT = "report:export"


#: Permissions that may only be exercised by a session that has completed a
#: second factor (AC-29.5). Reading is not on this list; changing who has
#: access, and moving money, are.
STEP_UP_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.ORG_UPDATE,
        Permission.ORG_TRANSFER_OWNERSHIP,
        Permission.MEMBER_INVITE,
        Permission.MEMBER_ROLE_CHANGE,
        Permission.MEMBER_REVOKE,
        Permission.BILLING_MANAGE,
    }
)

_MEMBER: frozenset[Permission] = frozenset(
    {
        Permission.ORG_READ,
        Permission.MEMBER_READ,
    }
)

#: Money, and the order history that explains it. Explicitly *not* people:
#: whoever pays the invoices has no business changing who can sign in.
_BILLING: frozenset[Permission] = _MEMBER | {
    Permission.BILLING_READ,
    Permission.BILLING_MANAGE,
    Permission.ORDER_READ,
    Permission.REPORT_READ,
}

_ADMINISTRATOR: frozenset[Permission] = _BILLING | {
    Permission.ORG_UPDATE,
    Permission.MEMBER_INVITE,
    Permission.MEMBER_ROLE_CHANGE,
    Permission.MEMBER_REVOKE,
    Permission.ORDER_PLACE,
    Permission.PEOPLE_READ,
    Permission.PEOPLE_MANAGE,
    Permission.REPORT_EXPORT,
}
# An administrator is deliberately *not* granted BILLING_MANAGE by inheritance
# alone -- it arrives above through _BILLING, which is intentional: an
# administrator who can place orders and cannot pay for them is not a workable
# role. Ownership transfer is the one thing they cannot do.
_ADMINISTRATOR = _ADMINISTRATOR - {Permission.ORG_TRANSFER_OWNERSHIP}

_OWNER: frozenset[Permission] = frozenset(Permission)

_MATRIX: dict[OrganizationRole, frozenset[Permission]] = {
    OrganizationRole.OWNER: _OWNER,
    OrganizationRole.ADMINISTRATOR: _ADMINISTRATOR,
    OrganizationRole.BILLING: _BILLING,
    OrganizationRole.MEMBER: _MEMBER,
}

_missing = set(OrganizationRole) - set(_MATRIX)
if _missing:  # pragma: no cover - guarded at import time
    raise RuntimeError(f"roles without a permission set: {sorted(_missing)}")


def permissions_for(role: OrganizationRole) -> frozenset[Permission]:
    try:
        return _MATRIX[role]
    except KeyError as exc:  # pragma: no cover - unreachable while the guard holds
        raise RuntimeError(f"no permission set declared for {role}") from exc


def requires_step_up(permission: Permission) -> bool:
    return permission in STEP_UP_PERMISSIONS
