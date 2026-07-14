from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from uuid import UUID

import boto3  # type: ignore[import-untyped]

from app.config import Settings


class InvoiceStorageError(Exception):
    pass


class InvoiceStorage(Protocol):
    def put(self, key: str, contents: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...


class FileSystemInvoiceStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise InvoiceStorageError("Invalid invoice object key")
        return path

    def put(self, key: str, contents: bytes) -> None:
        try:
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
        except OSError as exc:
            raise InvoiceStorageError("Invoice storage is unavailable") from exc

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except OSError as exc:
            raise InvoiceStorageError("Invoice is unavailable") from exc


class S3InvoiceStorage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.invoice_s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.invoice_s3_endpoint_url,
            aws_access_key_id=settings.invoice_s3_access_key_id,
            aws_secret_access_key=settings.invoice_s3_secret_access_key,
            region_name=settings.invoice_s3_region,
        )

    def put(self, key: str, contents: bytes) -> None:
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=contents,
                ContentType="application/pdf",
            )
        except Exception as exc:
            raise InvoiceStorageError("Invoice storage is unavailable") from exc

    def get(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return bytes(response["Body"].read())
        except Exception as exc:
            raise InvoiceStorageError("Invoice is unavailable") from exc


def build_invoice_storage(settings: Settings) -> InvoiceStorage:
    if settings.invoice_storage_backend == "s3":
        return S3InvoiceStorage(settings)
    return FileSystemInvoiceStorage(Path(settings.invoice_storage_path))


@dataclass(frozen=True)
class InvoiceDetails:
    order_id: UUID
    organization_name: str
    manifest_name: str
    tier_name: str
    pilgrim_count: int
    per_pilgrim_ngn: Decimal
    total_ngn: Decimal
    bank_name: str
    account_name: str
    account_number: str


class InvoicePDFGenerator:
    def render(self, details: InvoiceDetails) -> bytes:
        lines = [
            "DamDam HTO Invoice",
            f"Invoice: {details.order_id}",
            f"Organization: {details.organization_name}",
            f"Manifest: {details.manifest_name}",
            f"Package tier: {details.tier_name}",
            f"Pilgrims: {details.pilgrim_count}",
            f"Wholesale per pilgrim: NGN {details.per_pilgrim_ngn:,.2f}",
            f"Total due: NGN {details.total_ngn:,.2f}",
            "Payment method: Bank transfer",
            f"Bank: {details.bank_name}",
            f"Account name: {details.account_name}",
            f"Account number: {details.account_number}",
            "Use the invoice UUID as your payment reference.",
        ]
        content = ["BT", "/F1 12 Tf", "50 790 Td", "16 TL"]
        for index, line in enumerate(lines):
            if index:
                content.append("T*")
            content.append(f"({self._escape(line)}) Tj")
        content.append("ET")
        stream = "\n".join(content).encode("latin-1", errors="replace")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
                b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
            ),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream",
        ]
        document = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, body in enumerate(objects, start=1):
            offsets.append(len(document))
            document.extend(f"{number} 0 obj\n".encode())
            document.extend(body)
            document.extend(b"\nendobj\n")
        xref_offset = len(document)
        document.extend(f"xref\n0 {len(objects) + 1}\n".encode())
        document.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            document.extend(f"{offset:010d} 00000 n \n".encode())
        document.extend(
            (
                f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n"
            ).encode()
        )
        return bytes(document)

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
