"""Report what a US-30 retirement cleanup WOULD remove. Deletes nothing.

Chunk 04 withdrew the check-in, SOS, family-contact, arrival-geofence,
verified-caller-ID and app-calling behavior without touching a single row. The
data those features produced is still personal data, and deleting it is a
separate decision under the approved retention policy -- see
docs/implementation/retirement/RETENTION-PLAN.md and the founder gate in
docs/implementation/SCOPE-DISPOSITION.md.

This script exists so that decision can be taken against real numbers instead
of guesses. It opens a read-only session, counts rows, and prints a report. It
issues no DELETE, no UPDATE and no DDL, and it takes no argument that would let
it. Executing the plan is a separate, explicitly authorized step that does not
exist yet.

Usage:
    DATABASE_URL=... python scripts/retirement_dry_run.py [--json]
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence

from sqlalchemy import func
from sqlmodel import Session, create_engine, select

from app.auth.models import User
from app.checkins.models import CheckIn, CheckInNotification
from app.config import get_settings
from app.packages.models import DestinationGeofence
from app.profile.models import FamilyContact
from app.sos.models import SOSAlert, SOSNotification
from app.voice.models import CallerIdConsent, VerifiedCallerIdentity, VoiceCredential

# Every table the retirement leaves behind, with why it is still here.
RETIRED_TABLES: Sequence[tuple[str, type, str]] = (
    (
        "check_ins",
        CheckIn,
        "Welfare records, including locations not yet nulled by the retention "
        "sweep. Deletion is gated on the founder's check-in disposition.",
    ),
    ("check_in_notifications", CheckInNotification, "Delivery state for the above."),
    ("sos_alerts", SOSAlert, "Alert records with locations. Removal authorized."),
    ("sos_notifications", SOSNotification, "Delivery state for the above."),
    (
        "family_contacts",
        FamilyContact,
        "Third-party personal data: names and phone numbers of people who never "
        "used DamDam themselves. Removal authorized.",
    ),
    (
        "destination_geofences",
        DestinationGeofence,
        "Configuration, not personal data. Retained until the catalog work in "
        "chunk 09 supersedes it.",
    ),
    (
        "verified_caller_identities",
        VerifiedCallerIdentity,
        "Deferred, not retired (D2). Do not delete without a D2 decision.",
    ),
    (
        "caller_id_consents",
        CallerIdConsent,
        "Consent records are evidence. Keep for the statutory period even if "
        "the identities go.",
    ),
    (
        "voice_credentials",
        VoiceCredential,
        "SIP credentials for a retired app-calling path. No personal data "
        "beyond the link to a user; revoke provider-side before deleting.",
    ),
)


def counts(session: Session) -> list[dict[str, object]]:
    report: list[dict[str, object]] = []
    for name, model, note in RETIRED_TABLES:
        total = session.exec(select(func.count()).select_from(model)).one()
        report.append({"table": name, "rows": int(total), "note": note})
    return report


def locations_still_held(session: Session) -> int:
    """Check-in rows whose coordinates the retention sweep has not yet nulled."""
    return int(
        session.exec(
            select(func.count())
            .select_from(CheckIn)
            .where(
                (CheckIn.latitude.is_not(None))  # type: ignore[union-attr]
                | (CheckIn.longitude.is_not(None))  # type: ignore[union-attr]
            )
        ).one()
    )


def main() -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        report = counts(session)
        held = locations_still_held(session)
        users = int(session.exec(select(func.count()).select_from(User)).one())

    if "--json" in sys.argv:
        print(json.dumps({"tables": report, "checkin_locations_held": held}, indent=2))
        return 0

    print("US-30 retirement dry run -- NOTHING IS DELETED BY THIS SCRIPT")
    print(f"accounts on this database: {users}\n")
    width = max(len(row["table"]) for row in report)  # type: ignore[arg-type]
    for row in report:
        print(f"  {str(row['table']):<{width}}  {row['rows']:>8}  {row['note']}")
    print(f"\ncheck-in rows still holding coordinates: {held}")
    print(
        "\nNo row was modified. See docs/implementation/retirement/"
        "RETENTION-PLAN.md for what executing this would require."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
