"""Turn an uploaded PDF into a Bill, and check the arithmetic on every bill.

Bill Pay is the primary path and never comes through here: Ramp's OCR has
already produced line items. This module only serves UploadSource, plus the
math checks that run on bills from any source.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pdfplumber
from pydantic import BaseModel

from .config import LINE_TOLERANCE, TOTAL_TOLERANCE, Settings
from .llm import call_tool
from .models import (
    Bill,
    BillMathCheck,
    LineItem,
    LineMathResult,
    Usage,
    VendorRef,
    money,
)

logging.getLogger("pdfminer").setLevel(logging.ERROR)

LINE_TOL = Decimal(LINE_TOLERANCE)
TOTAL_TOL = Decimal(TOTAL_TOLERANCE)

# A line item row ends in qty, unit price, amount. Three column orders occur.
_MONEY = r"-?\$[\d,]+\.\d{2}"
_SKU = r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*"
_QTY = r"\d+(?:\.\d+)?"
_ROW_SKU_FIRST = re.compile(rf"^({_SKU})\s+(.+?)\s+({_QTY})\s+({_MONEY})\s+({_MONEY})$")
_ROW_DESC_FIRST = re.compile(rf"^(.+?)\s+({_SKU})\s+({_QTY})\s+({_MONEY})\s+({_MONEY})$")
_ROW_QTY_FIRST = re.compile(rf"^({_QTY})\s+({_SKU})\s+(.+?)\s+({_MONEY})\s+({_MONEY})$")
_INVOICE_NO = re.compile(r"[A-Z]{2,4}(?:-CM)?-\d{6}-\d{3}")
_DATE = r"[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}"
_ISSUED = re.compile(rf"(?<!Due )Date\s+({_DATE})")
_DUE = re.compile(rf"Due date\s+({_DATE})")
_TOTAL = re.compile(rf"(?:Total due|Credit total)\s+({_MONEY})")
_TAX = re.compile(rf"Sales tax\s+\(([\d.]+)%\)\s+({_MONEY})")
_CHARGE_CODES = {"SURCHG", "FREIGHT", "SHIP", "FUEL", "TAX", "ADJ", "S301", "CREDIT", "OFRT", "DUTY", "BRKG"}

UNREADABLE = "could not read"


def check_math(bill: Bill) -> Bill:
    """qty * unit_price = amount (±$0.02) and the lines sum to the total (±$0.05)."""
    results: list[LineMathResult] = []
    for line in bill.line_items:
        computed = money(line.quantity * line.unit_price)
        delta = money(abs(computed - line.amount))
        results.append(
            LineMathResult(
                line_index=line.line_index,
                ok=delta <= LINE_TOL,
                computed=computed,
                stated=line.amount,
                delta=delta,
            )
        )
    lines_sum = money(sum((line.amount for line in bill.line_items), Decimal("0")))
    total_delta = money(abs(lines_sum - bill.amount))
    check = BillMathCheck(
        lines_ok=all(r.ok for r in results),
        total_ok=total_delta <= TOTAL_TOL,
        lines_sum=lines_sum,
        stated_total=bill.amount,
        total_delta=total_delta,
        line_results=results,
    )
    return bill.model_copy(update={"math": check})


def parse_upload(path: Path, settings: Settings, usage: Usage) -> Bill:
    text, pages = _read_pdf(path)
    if len(text.strip()) < 40:
        return _unreadable(path, pages, settings, usage, scanned=True)
    try:
        bill = _bill_from_text(path, text, pages)
    except ValueError:
        return _unreadable(path, pages, settings, usage, scanned=False)
    bill = check_math(bill)
    if bill.math and bill.math.failed:
        # The text was there but the rows don't add up. Same fallback as a failed parse.
        return _unreadable(path, pages, settings, usage, scanned=False)
    return bill


def _read_pdf(path: Path) -> tuple[str, int]:
    with pdfplumber.open(path) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        return text, len(pdf.pages)


def _unreadable(path: Path, pages: int, settings: Settings, usage: Usage, scanned: bool) -> Bill:
    if settings.use_demo:
        # A demo must not fail closed on a scan. A person reviews it.
        return _shell_bill(path, pages, scanned, needs_review=True, review_reason=UNREADABLE)
    extracted = _extract_with_model(path, settings, usage)
    extracted = extracted.model_copy(update={"document_is_scanned_image": scanned, "page_count": pages})
    return check_math(extracted)


def _shell_bill(path: Path, pages: int, scanned: bool, needs_review: bool, review_reason: str) -> Bill:
    return Bill(
        id=_bill_id(path),
        vendor=VendorRef(id=f"ven_upload_{_digest(path)[:8]}", name="Unknown vendor"),
        invoice_number=path.stem,
        issued_at=date(1970, 1, 1),
        amount=Decimal("0.00"),
        line_items=[],
        document_url=str(path),
        document_is_scanned_image=scanned,
        page_count=pages,
        needs_review=needs_review,
        review_reason=review_reason,
        source="upload",
        status="UPLOADED",
    )


def _bill_from_text(path: Path, text: str, pages: int) -> Bill:
    number = _INVOICE_NO.search(text)
    total = _TOTAL.search(text)
    issued = _ISSUED.search(text)
    if not (number and total and issued):
        raise ValueError("header not found")
    lines = _parse_lines(text)
    tax = _TAX.search(text)
    if tax and not any(line.sku == "TAX" for line in lines):
        amount = _parse_money(tax.group(2))
        if amount:
            lines.append(
            LineItem(
                line_index=len(lines),
                sku="TAX",
                description=f"Sales tax ({tax.group(1)}%)",
                quantity=Decimal("1"),
                unit_price=amount,
                amount=amount,
            )
        )
    if not lines:
        raise ValueError("no line items")
    due = _DUE.search(text)
    return Bill(
        id=_bill_id(path),
        vendor=VendorRef(id=f"ven_upload_{_digest(path)[:8]}", name=_vendor_name(text)),
        invoice_number=number.group(0),
        issued_at=_parse_date(issued.group(1)),
        due_at=_parse_date(due.group(1)) if due else None,
        amount=_parse_money(total.group(1)),
        line_items=lines,
        document_url=str(path),
        document_is_scanned_image=False,
        page_count=pages,
        source="upload",
        status="UPLOADED",
    )


_STOP_CONTINUATION = re.compile(
    r"^(Subtotal|Sales tax|Total|Credit total|Please |Terms|ACH |SKU |Qty |Description )|\bPage\s+\d"
)


def _parse_lines(text: str) -> list[LineItem]:
    items: list[LineItem] = []
    in_totals = False
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        if line.startswith("Subtotal"):
            in_totals = True
        if in_totals:
            continue
        parsed = _parse_row(line)
        if parsed is not None:
            sku, description, qty, unit_price, amount = parsed
            items.append(
                LineItem(
                    line_index=len(items),
                    sku=sku,
                    description=description,
                    quantity=qty,
                    unit_price=unit_price,
                    amount=amount,
                )
            )
            continue
        # A wrapped description spills onto the next line with no prices.
        if items and "$" not in line and not _STOP_CONTINUATION.search(line):
            items[-1] = items[-1].model_copy(update={"description": f"{items[-1].description} {line}"})
    return items


def _parse_row(line: str) -> tuple[str, str, Decimal, Decimal, Decimal] | None:
    """Pick the column order whose SKU is a real code and whose math holds."""
    candidates: list[tuple[str, str, Decimal, Decimal, Decimal]] = []
    qty_first = _ROW_QTY_FIRST.match(line)
    if qty_first and _starts_with_qty(line):
        qty, sku, desc, unit, amount = qty_first.groups()
        candidates.append((_clean_sku(sku), desc.strip(), *_numbers(qty, unit, amount)))
    sku_first = _ROW_SKU_FIRST.match(line)
    if sku_first and _starts_with_sku(line):
        sku, desc, qty, unit, amount = sku_first.groups()
        candidates.append((_clean_sku(sku), desc.strip(), *_numbers(qty, unit, amount)))
    desc_first = _ROW_DESC_FIRST.match(line)
    if desc_first:
        desc, sku, qty, unit, amount = desc_first.groups()
        candidates.append((_clean_sku(sku), desc.strip(), *_numbers(qty, unit, amount)))
    for sku, desc, qty, unit, amount in candidates:
        if abs(qty * unit - amount) <= LINE_TOL and desc:
            return sku, desc, qty, unit, amount
    return None


def _starts_with_qty(line: str) -> bool:
    return bool(re.match(rf"{_QTY}\s+{_SKU}\s", line))


def _starts_with_sku(line: str) -> bool:
    token = line.split(" ", 1)[0]
    if "-" in token and re.fullmatch(_SKU, token):
        return True
    return token in _CHARGE_CODES


def _numbers(qty: str, unit: str, amount: str) -> tuple[Decimal, Decimal, Decimal]:
    return Decimal(qty), _parse_money(unit), _parse_money(amount)


def _clean_sku(sku: str) -> str:
    return sku.rstrip(".").upper()


def _parse_money(raw: str) -> Decimal:
    negative = raw.strip().startswith("-")
    number = Decimal(raw.replace("$", "").replace(",", "").replace("-", ""))
    return money(-number if negative else number)


def _parse_date(raw: str) -> date:
    return datetime.strptime(raw, "%b %d, %Y").date()


def _vendor_name(text: str) -> str:
    for raw in text.splitlines():
        line = raw.strip()
        if line:
            name = re.sub(r"\b(INVOICE|CREDIT MEMO)\b", "", line, flags=re.I).strip(" -")
            if name.isupper():
                name = name.title()
            return name
    return "Unknown vendor"


def _bill_id(path: Path) -> str:
    return f"bill_upload_{_digest(path)[:12]}"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- live model fallback --------------------------------------------------- #


class _Extracted(BaseModel):
    vendor_name: str
    invoice_number: str
    issued_at: date
    due_at: date | None = None
    total: Decimal
    line_items: list[LineItem]


_EXTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "vendor_name": {"type": "string"},
        "invoice_number": {"type": "string"},
        "issued_at": {"type": "string", "description": "YYYY-MM-DD"},
        "due_at": {"type": ["string", "null"]},
        "total": {"type": "number"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "line_index": {"type": "integer"},
                    "sku": {"type": "string"},
                    "description": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number"},
                    "amount": {"type": "number"},
                },
                "required": ["line_index", "sku", "description", "quantity", "unit_price", "amount"],
            },
        },
    },
    "required": ["vendor_name", "invoice_number", "issued_at", "due_at", "total", "line_items"],
}


def _extract_with_model(path: Path, settings: Settings, usage: Usage) -> Bill:
    encoded = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    content = [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": encoded}},
        {
            "type": "text",
            "text": (
                "Extract this invoice. One entry per line item including freight, surcharges, "
                "and sales tax. Copy descriptions verbatim. Do not compute new amounts."
            ),
        },
    ]
    extracted = call_tool(
        settings,
        settings.tier1_model,
        "You extract invoice line items into the provided tool. You never invent rows.",
        content,
        "extract_invoice",
        "Return the invoice header and every line item.",
        _EXTRACT_SCHEMA,
        _Extracted,
        usage,
    )
    assert isinstance(extracted, _Extracted)
    return Bill(
        id=_bill_id(path),
        vendor=VendorRef(id=f"ven_upload_{_digest(path)[:8]}", name=extracted.vendor_name),
        invoice_number=extracted.invoice_number,
        issued_at=extracted.issued_at,
        due_at=extracted.due_at,
        amount=money(extracted.total),
        line_items=extracted.line_items,
        document_url=str(path),
        source="upload",
        status="UPLOADED",
    )
