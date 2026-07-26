import csv
import io
from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete
from sqlmodel import Session, col, select

from app.auth.models import (
    Locale,
    Manifest,
    ManifestPilgrim,
    ManifestStatus,
    ManifestValidationStatus,
    Organization,
)
from app.auth.schemas import to_e164, validate_nigerian_phone
from app.manifests.schemas import (
    ManifestIssue,
    ManifestPreviewRow,
    ManifestUploadResponse,
)

MAX_MANIFEST_ROWS = 500
REQUIRED_COLUMNS = {"first_name", "last_name", "phone_number"}


class ManifestError(Exception):
    def __init__(self, code: str, details: dict[str, object] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


@dataclass
class ParsedRow:
    row_number: int
    first_name: str
    last_name: str
    phone_number: str
    passport_number: str | None
    seat_number: str | None
    locale: Locale | None
    errors: list[str]


class ManifestService:
    def create(
        self, session: Session, organization_id: UUID, name: str | None
    ) -> Manifest:
        manifest = Manifest(organization_id=organization_id, name=name)
        session.add(manifest)
        session.commit()
        session.refresh(manifest)
        return manifest

    def upload(
        self,
        session: Session,
        organization_id: UUID,
        manifest_id: UUID,
        filename: str | None,
        contents: bytes,
    ) -> ManifestUploadResponse:
        manifest = self._owned_draft(session, organization_id, manifest_id)
        organization = session.get(Organization, organization_id)
        assert organization is not None
        if filename is None or not filename.lower().endswith(".csv"):
            raise ManifestError("csv_required")
        rows = self._parse(contents)

        phone_counts = Counter(
            row.phone_number for row in rows if row.phone_number and not row.errors
        )
        session.execute(
            delete(ManifestPilgrim).where(
                col(ManifestPilgrim.manifest_id) == manifest.id
            )
        )

        stored: list[ManifestPilgrim] = []
        invalid_rows: list[ManifestIssue] = []
        for row in rows:
            if row.errors:
                reason = "; ".join(row.errors)
                status = ManifestValidationStatus.INVALID
                invalid_rows.append(
                    ManifestIssue(row_number=row.row_number, reason=reason)
                )
            elif phone_counts[row.phone_number] > 1:
                reason = "Duplicate phone number in this manifest"
                status = ManifestValidationStatus.DUPLICATE_WARNING
            else:
                reason = None
                status = ManifestValidationStatus.VALID
            pilgrim = ManifestPilgrim(
                manifest_id=manifest.id,
                first_name=row.first_name[:100],
                last_name=row.last_name[:100],
                phone_number=row.phone_number[:14],
                passport_number=(row.passport_number or None),
                seat_number=(row.seat_number or None),
                locale=row.locale or organization.locale,
                row_number=row.row_number,
                validation_status=status,
                validation_error=reason[:255] if reason else None,
            )
            session.add(pilgrim)
            stored.append(pilgrim)

        manifest.total_rows = len(rows)
        manifest.valid_rows = len(rows) - len(invalid_rows)
        session.add(manifest)
        session.commit()
        for pilgrim in stored:
            session.refresh(pilgrim)

        preview = [
            ManifestPreviewRow(
                id=pilgrim.id,
                row_number=pilgrim.row_number,
                first_name=pilgrim.first_name,
                last_name=pilgrim.last_name,
                phone_number=pilgrim.phone_number,
                passport_number=pilgrim.passport_number,
                seat_number=pilgrim.seat_number,
                validation_status=pilgrim.validation_status,
                warning=(
                    pilgrim.validation_error
                    if pilgrim.validation_status
                    == ManifestValidationStatus.DUPLICATE_WARNING
                    else None
                ),
            )
            for pilgrim in stored
            if pilgrim.validation_status != ManifestValidationStatus.INVALID
        ]
        return ManifestUploadResponse(
            total_rows=len(rows),
            valid_rows=manifest.valid_rows,
            invalid_rows=invalid_rows,
            preview=preview,
        )

    def confirm(
        self, session: Session, organization_id: UUID, manifest_id: UUID
    ) -> Manifest:
        manifest = self._owned_draft(session, organization_id, manifest_id)
        if manifest.valid_rows == 0:
            raise ManifestError("no_valid_rows")
        session.execute(
            delete(ManifestPilgrim).where(
                col(ManifestPilgrim.manifest_id) == manifest.id,
                col(ManifestPilgrim.validation_status)
                == ManifestValidationStatus.INVALID,
            )
        )
        manifest.status = ManifestStatus.VALIDATED
        session.add(manifest)
        session.commit()
        session.refresh(manifest)
        return manifest

    def list_manifests(self, session: Session, organization_id: UUID) -> list[Manifest]:
        return list(
            session.exec(
                select(Manifest)
                .where(Manifest.organization_id == organization_id)
                .order_by(col(Manifest.created_at).desc())
            ).all()
        )

    def _owned_draft(
        self, session: Session, organization_id: UUID, manifest_id: UUID
    ) -> Manifest:
        manifest = session.exec(
            select(Manifest).where(
                Manifest.id == manifest_id,
                Manifest.organization_id == organization_id,
            )
        ).first()
        if manifest is None:
            raise ManifestError("manifest_not_found")
        if manifest.status != ManifestStatus.DRAFT:
            raise ManifestError("manifest_already_confirmed")
        return manifest

    def _parse(self, contents: bytes) -> list[ParsedRow]:
        try:
            text = contents.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ManifestError("malformed_csv") from exc
        if not text.strip() or "\x00" in text:
            raise ManifestError("malformed_csv")
        try:
            reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
            headers = reader.fieldnames
            if headers is None:
                raise ManifestError("malformed_csv")
            normalized_headers = [header.strip() for header in headers]
            if len(set(normalized_headers)) != len(normalized_headers):
                raise ManifestError("malformed_csv")
            missing = REQUIRED_COLUMNS - set(normalized_headers)
            if missing:
                raise ManifestError("missing_required_columns")
            reader.fieldnames = normalized_headers
            raw_rows = list(reader)
        except ManifestError:
            raise
        except (csv.Error, UnicodeError) as exc:
            raise ManifestError("malformed_csv") from exc
        if len(raw_rows) > MAX_MANIFEST_ROWS:
            raise ManifestError("row_limit_exceeded")

        rows: list[ParsedRow] = []
        for index, raw in enumerate(raw_rows, start=2):
            errors: list[str] = []
            if None in raw:
                errors.append("Row has more values than the header")
            first_name = (raw.get("first_name") or "").strip()
            last_name = (raw.get("last_name") or "").strip()
            raw_phone = (raw.get("phone_number") or "").strip()
            passport = (raw.get("passport_number") or "").strip() or None
            seat = (raw.get("seat_number") or "").strip() or None
            raw_locale = (raw.get("locale") or "").strip().lower()
            locale: Locale | None = None
            if raw_locale:
                try:
                    locale = Locale(raw_locale)
                except ValueError:
                    errors.append("locale must be en or fr")
            if not first_name:
                errors.append("first_name is required")
            elif len(first_name) > 100:
                errors.append("first_name must be at most 100 characters")
            if not last_name:
                errors.append("last_name is required")
            elif len(last_name) > 100:
                errors.append("last_name must be at most 100 characters")
            try:
                validate_nigerian_phone(raw_phone)
                phone_number = to_e164(raw_phone)
            except ValueError:
                phone_number = raw_phone
                errors.append("phone_number must be an 11-digit Nigerian mobile number")
            if passport is not None and len(passport) > 50:
                errors.append("passport_number must be at most 50 characters")
                passport = passport[:50]
            if seat is not None and len(seat) > 10:
                errors.append("seat_number must be at most 10 characters")
                seat = seat[:10]
            rows.append(
                ParsedRow(
                    row_number=index,
                    first_name=first_name,
                    last_name=last_name,
                    phone_number=phone_number,
                    passport_number=passport,
                    seat_number=seat,
                    locale=locale,
                    errors=errors,
                )
            )
        return rows
