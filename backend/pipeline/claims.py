"""Roll labeled lines and price findings up into one claim per vendor.

All of the arithmetic is here. Refundable dollars are pre-tax IEEPA surcharges
inside the window, plus the expected price claim, minus vendor credits already
on the account. Section 232 and Section 301 are tracked, not claimed.
Importer-of-record duty is excluded; it belongs to CBP.

Evidence tier, strongest first:
- Documented: an invoice line names a tariff, a duty, or IEEPA.
- Contract + price: a contract allows duty pass-through or refund sharing, and
  a price increase passed every required test.
- Price-only: no document. The price increase passed every required test.

Strength:
- High: Documented with a refund clause, or Contract + price that also reverted.
- Medium: Documented without a clause, or Contract + price that did not revert.
- Low: Price-only, or any price claim whose refundable dollars rest only on an
  inferred country of origin.
- Tracked: nothing refundable, but a non-refundable tariff line.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from .config import WINDOW_END, WINDOW_START
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
    price_findings = [finding for finding in prices.findings if finding.vendor_name == name]
    inferred_only = excess > 0 and ieepa <= 0 and all(finding.origin_inferred for finding in price_findings)
    tier, reasons = _tier(explicit, clause, excess > 0, inferred_only)
    low, expected, high = _price_range(price_findings) if excess > 0 else (None, None, None)
    address = []
    if vendor and vendor.address:
        address = [line for line in (vendor.address.line1, vendor.address.line2) if line]
    return VendorClaim(
        vendor_id=vendor.id if vendor else "",
        vendor_name=name,
        contact_email=vendor.contact_email if vendor else None,
        address_lines=address,
        strength=_strength(gross, non_refundable, tier, clause, reverted, inferred_only),
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
        evidence_tier=tier,
        tier_reasons=reasons,
        claim_low=low,
        claim_expected=expected,
        claim_high=high,
        origin_inferred_only=inferred_only,
    )


def _tier(explicit: bool, clause: bool, price: bool, inferred_only: bool) -> tuple[str | None, list[str]]:
    if explicit:
        reasons = ["An invoice line or supplier notice names a tariff, a duty, or IEEPA."]
        if clause:
            reasons.append("The contract also allows a duty pass-through or a shared refund.")
        return "documented", reasons
    if price and clause:
        reasons = [
            "The contract allows a duty pass-through or a shared refund.",
            "A price increase passed every required test.",
        ]
        if inferred_only:
            reasons.append("Country of origin was inferred, not printed on the invoice, so strength is capped at Low.")
        return "contract_price", reasons
    if price:
        reasons = [
            "No invoice line or contract names the tariff.",
            "The price increase passed every required test, so the claim rests on the price alone.",
        ]
        if inferred_only:
            reasons.append("Country of origin was inferred, not printed on the invoice, so strength is capped at Low.")
        return "price_only", reasons
    return None, []


def _price_range(findings) -> tuple[Decimal, Decimal, Decimal]:
    low = money(sum((finding.low_amount for finding in findings), Decimal("0")))
    expected = money(sum((finding.amount for finding in findings), Decimal("0")))
    high = money(sum((finding.high_amount for finding in findings), Decimal("0")))
    return low, expected, high


def _strength(gross, non_refundable, tier, clause, reverted, inferred_only) -> ClaimStrength | None:
    if gross <= 0:
        return ClaimStrength.tracked if non_refundable > 0 else None
    if inferred_only:
        return ClaimStrength.low
    if tier == "documented" and clause:
        return ClaimStrength.high
    if tier == "documented":
        return ClaimStrength.medium
    if tier == "contract_price" and clause and reverted:
        return ClaimStrength.high
    if tier == "contract_price":
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
