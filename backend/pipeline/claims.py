"""Roll labeled lines and price findings up into one claim per vendor.

All of the arithmetic is here. Refundable dollars are pre-tax IEEPA surcharges
inside the window, plus capped price excess, minus vendor credits already on
the account. Section 301 and other non-IEEPA tariffs are tracked, not claimed.
Importer-of-record duty is excluded; it belongs to CBP.

Strength:
- High: an explicit IEEPA surcharge and a contract clause that pays it back.
- Medium: an explicit surcharge with no clause, or a price jump that reverted
  and a clause that passes the refund through.
- Low: a price jump with nothing else behind it.
- Tracked: non-refundable tariff lines only. Nothing to bill the supplier for.
"""

from __future__ import annotations

from decimal import Decimal

from .config import WINDOW_END, WINDOW_START
from typing import Literal

from .models import (
    Bill,
    ClaimStrength,
    ContractFinding,
    Evidence,
    ImporterCase,
    LineCategory,
    LineLabel,
    PriceAnalysis,
    Vendor,
    VendorClaim,
    VendorCredit,
    money,
)

EvidenceType = Literal["tariff_ieepa_surcharge", "price_excess", "tariff_other", "vendor_credit"]

_CREDIT_WORDS = ("tariff", "surcharge", "ieepa", "duty")


def build(
    bills: list[Bill],
    vendors: list[Vendor],
    labels: list[LineLabel],
    prices: PriceAnalysis,
    credits: list[VendorCredit],
    contracts: dict[str, ContractFinding],
    importer_cases: list[ImporterCase],
) -> list[VendorClaim]:
    label_of = {(label.invoice_number, label.line_index): label for label in labels}
    importer_lines = {(case.invoice_number, case.line_index) for case in importer_cases}
    by_vendor = {vendor.name: vendor for vendor in vendors}

    evidence: dict[str, list[Evidence]] = {name: [] for name in by_vendor}
    for bill in bills:
        in_window = WINDOW_START <= bill.issued_at <= WINDOW_END
        for line in bill.line_items:
            if (bill.invoice_number, line.line_index) in importer_lines:
                continue
            label = label_of.get((bill.invoice_number, line.line_index))
            if label is None or not in_window:
                continue
            if label.category is LineCategory.tariff_ieepa:
                evidence.setdefault(bill.vendor.name, []).append(
                    _item(bill, line.line_index, line.description, line.amount, "tariff_ieepa_surcharge", label.labeled_by)
                )
            elif label.category is LineCategory.tariff_other:
                evidence.setdefault(bill.vendor.name, []).append(
                    _item(bill, line.line_index, line.description, line.amount, "tariff_other", label.labeled_by)
                )

    for finding in prices.findings:
        evidence.setdefault(finding.vendor_name, []).append(
            Evidence(
                invoice_number=finding.invoice_number,
                line_index=finding.line_index,
                date=finding.issued_at,
                description=finding.description,
                amount=finding.amount,
                type="price_excess",
                labeled_by=finding.labeled_by,
            )
        )

    for credit in credits:
        if not _is_tariff_credit(credit):
            continue
        evidence.setdefault(credit.vendor.name, []).append(
            Evidence(
                invoice_number=credit.credit_memo_number,
                line_index=0,
                date=credit.issued_at,
                description=credit.memo or credit.reference or "Vendor credit",
                amount=money(-credit.amount),
                type="vendor_credit",
                labeled_by="bill_pay",
            )
        )

    claims = []
    names = list(by_vendor) or list(evidence)
    for name in names:
        vendor = by_vendor.get(name)
        items = sorted(evidence.get(name, []), key=lambda item: (item.date, item.invoice_number, item.line_index))
        contract = contracts.get(name)
        claims.append(_claim(name, vendor, items, prices, contract))
    return claims


def _claim(name, vendor, items, prices, contract) -> VendorClaim:
    ieepa = _sum(items, "tariff_ieepa_surcharge")
    excess = _sum(items, "price_excess")
    credits = -_sum(items, "vendor_credit")
    gross = money(ieepa + excess)
    refundable = money(gross - credits)
    non_refundable = _sum(items, "tariff_other")
    reverted = _reverted(name, prices)
    explicit = ieepa > 0
    mentions = bool(contract and contract.mentions_tariffs)
    clause = bool(contract and contract.refund_or_credit_clause)
    address = []
    if vendor and vendor.address:
        address = [line for line in (vendor.address.line1, vendor.address.line2) if line]
    return VendorClaim(
        vendor_id=vendor.id if vendor else "",
        vendor_name=name,
        contact_email=vendor.contact_email if vendor else None,
        address_lines=address,
        strength=_strength(gross, non_refundable, explicit, reverted, clause),
        refundable_total=refundable,
        gross_refundable=gross,
        ieepa_surcharge_total=ieepa,
        price_excess_total=excess,
        credits_applied=credits,
        non_refundable_total=non_refundable,
        explicit_surcharge=explicit,
        price_jump_reverted=reverted,
        contract_mentions_tariffs=mentions,
        contract_refund_clause=clause,
        clause_number=contract.clause_number if contract else None,
        clause_text=contract.clause_text if contract else None,
        evidence=items,
    )


def _strength(gross, non_refundable, explicit, reverted, clause) -> ClaimStrength | None:
    if gross <= 0:
        return ClaimStrength.tracked if non_refundable > 0 else None
    if explicit and clause:
        return ClaimStrength.high
    if explicit or (reverted and clause):
        return ClaimStrength.medium
    return ClaimStrength.low


def _reverted(vendor: str, prices: PriceAnalysis) -> bool | None:
    flagged = [sku for sku in prices.skus if sku.vendor_name == vendor and sku.flagged_amount > 0]
    if not flagged:
        return None
    known = [sku.fell_back_after_window for sku in flagged if sku.fell_back_after_window is not None]
    if not known:
        return None
    return all(known)


def _sum(items: list[Evidence], kind: str) -> Decimal:
    return money(sum((item.amount for item in items if item.type == kind), Decimal("0")))


def _is_tariff_credit(credit: VendorCredit) -> bool:
    text = f"{credit.memo or ''} {credit.reference or ''}".lower()
    return any(word in text for word in _CREDIT_WORDS)


def _item(bill: Bill, line_index: int, description: str, amount: Decimal, kind: EvidenceType, labeled_by: str) -> Evidence:
    return Evidence(
        invoice_number=bill.invoice_number,
        line_index=line_index,
        date=bill.issued_at,
        description=description,
        amount=amount,
        type=kind,
        labeled_by=labeled_by,
    )
