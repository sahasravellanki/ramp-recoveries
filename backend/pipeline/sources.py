"""Where bills come from.

MockBillPaySource stands in for Ramp's API: Bill Pay has already run OCR, so the
line items arrive structured and no PDF parsing happens. UploadSource is the
exception, for a PDF a person drops in. QuickBooks is a stub.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from .config import Settings, get_settings
from .ingest import check_math, parse_upload
from .models import Bill, Usage, Vendor, VendorCredit, VendorRef


def _load(path: Path) -> object:
    return json.loads(path.read_text(), parse_float=Decimal)


class BillSource(Protocol):
    def get_bills(self) -> list[Bill]: ...

    def get_vendors(self) -> list[Vendor]: ...


class MockBillPaySource:
    """Reads the generated Ramp-shaped fixtures. This is the primary path."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def get_bills(self) -> list[Bill]:
        bills = [Bill.model_validate(raw) for raw in _load(self.data_dir / "bills.json")]
        return [check_math(bill) for bill in bills]

    def get_vendors(self) -> list[Vendor]:
        return [Vendor.model_validate(raw) for raw in _load(self.data_dir / "vendors.json")]

    def get_vendor_credits(self) -> list[VendorCredit]:
        return [VendorCredit.model_validate(raw) for raw in _load(self.data_dir / "vendor_credits.json")]


class UploadSource:
    """PDFs a user uploaded. Line items come from ingest, not from Bill Pay."""

    def __init__(self, paths: list[Path], settings: Settings | None = None, usage: Usage | None = None):
        self.paths = [Path(p) for p in paths]
        self.settings = settings or get_settings()
        self.usage = usage or Usage()
        self._bills: list[Bill] | None = None

    def get_bills(self) -> list[Bill]:
        if self._bills is None:
            self._bills = [parse_upload(path, self.settings, self.usage) for path in self.paths]
        return self._bills

    def get_vendors(self) -> list[Vendor]:
        seen: dict[str, Vendor] = {}
        for bill in self.get_bills():
            seen.setdefault(
                bill.vendor.name,
                Vendor(id=bill.vendor.id, name=bill.vendor.name),
            )
        return list(seen.values())


class QuickBooksSource:
    """TODO: pull Bill, Vendor, and VendorCredit from the QuickBooks Online API.

    Needs OAuth against the company's realm, then a query on those three
    entities mapped into Bill / Vendor / VendorCredit. Not wired up; the demo
    runs entirely on MockBillPaySource.
    """

    def get_bills(self) -> list[Bill]:
        raise NotImplementedError("TODO: QuickBooks Online bills are not connected.")

    def get_vendors(self) -> list[Vendor]:
        raise NotImplementedError("TODO: QuickBooks Online vendors are not connected.")

    def get_vendor_credits(self) -> list[VendorCredit]:
        raise NotImplementedError("TODO: QuickBooks Online vendor credits are not connected.")


# Re-exported so callers can build a vendor ref without importing models.
__all__ = ["BillSource", "MockBillPaySource", "UploadSource", "QuickBooksSource", "VendorRef"]
