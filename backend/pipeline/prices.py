"""Price pass-throughs, computed with pandas. No model is involved.

Baseline is the median unit price before the tariff window. Expected price is
that baseline grown at 3% a year. Inside the window, a line is flagged when the
price beats the expected price by more than 5%, the SKU is imported_likely, and
the excess is capped at the category's IEEPA rate. Dollars are Decimal; pandas
only lines the rows up.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd

from .config import WINDOW_END, WINDOW_START
from .models import Bill, LineCategory, LineLabel, PriceAnalysis, PriceFinding, SkuPriceSummary, SkuTag, money

GROWTH = Decimal("0.03")
THRESHOLD = Decimal("0.05")
# A mock benchmark, deliberately not the baseline, and never used in the claim.
BENCHMARK_FACTOR = Decimal("0.99")


def analyze(
    bills: list[Bill],
    labels: list[LineLabel],
    tags: dict[tuple[str, str], SkuTag],
) -> PriceAnalysis:
    label_of = {(label.invoice_number, label.line_index): label for label in labels}
    rows = []
    for bill in bills:
        for line in bill.line_items:
            label = label_of.get((bill.invoice_number, line.line_index))
            if label is None or label.category is not LineCategory.product:
                continue
            tag = tags.get((bill.vendor.name, line.sku))
            rows.append(
                {
                    "vendor": bill.vendor.name,
                    "sku": line.sku,
                    "invoice_number": bill.invoice_number,
                    "line_index": line.line_index,
                    "issued": bill.issued_at,
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "imported": bool(tag and tag.imported_likely),
                    "rate": tag.ieepa_rate if tag else Decimal("0"),
                    "category_id": tag.category_id if tag else None,
                    "labeled_by": tag.labeled_by if tag else "unlabeled",
                }
            )
    if not rows:
        return PriceAnalysis(findings=[], skus=[])

    frame = pd.DataFrame(rows)
    frame["issued"] = pd.to_datetime(frame["issued"])
    # Median needs a numeric column. The claim itself is computed in Decimal below.
    frame["unit_price_num"] = frame["unit_price"].map(float)
    before = frame[frame["issued"] < pd.Timestamp(WINDOW_START)]
    baselines = before.groupby(["vendor", "sku"])["unit_price_num"].median()
    after = frame[frame["issued"] > pd.Timestamp(WINDOW_END)]
    post = after.groupby(["vendor", "sku"])["unit_price_num"].median()

    findings: list[PriceFinding] = []
    flagged_by_sku: dict[tuple[str, str], Decimal] = {}
    window = frame[(frame["issued"] >= pd.Timestamp(WINDOW_START)) & (frame["issued"] <= pd.Timestamp(WINDOW_END))]
    for record in window.to_dict("records"):
        key = (record["vendor"], record["sku"])
        if key not in baselines.index:
            continue
        baseline = _cents(baselines.loc[key])
        issued = record["issued"].date()
        expected = _expected(baseline, issued)
        unit_price = record["unit_price"]
        if not record["imported"] or unit_price <= expected * (1 + THRESHOLD):
            continue
        excess = unit_price - expected
        cap = baseline * record["rate"]
        capped = min(excess, cap)
        amount = money(capped * record["quantity"])
        if amount <= 0:
            continue
        findings.append(
            PriceFinding(
                vendor_name=record["vendor"],
                sku=record["sku"],
                invoice_number=record["invoice_number"],
                line_index=int(record["line_index"]),
                issued_at=issued,
                description=record["description"],
                quantity=record["quantity"],
                unit_price=unit_price,
                baseline=baseline,
                expected=money(expected),
                excess_per_unit=money(excess),
                capped_per_unit=money(capped),
                amount=amount,
                category_id=record["category_id"] or "",
                tariff_rate=record["rate"],
                labeled_by=record["labeled_by"],
            )
        )
        flagged_by_sku[key] = flagged_by_sku.get(key, Decimal("0.00")) + amount

    skus: list[SkuPriceSummary] = []
    counts = frame.groupby(["vendor", "sku"]).size()
    keys = sorted(set(baselines.index).union(counts.index))
    for key in keys:
        vendor, sku = key
        baseline = _cents(baselines.loc[key]) if key in baselines.index else None
        fell_back = None
        if baseline is not None and key in flagged_by_sku:
            if key in post.index:
                fell_back = _cents(post.loc[key]) <= money(baseline * (1 + THRESHOLD))
        skus.append(
            SkuPriceSummary(
                vendor_name=vendor,
                sku=sku,
                baseline=baseline,
                observations=int(counts.loc[key]),
                benchmark_price=money(baseline * BENCHMARK_FACTOR) if baseline is not None else None,
                fell_back_after_window=fell_back,
                flagged_amount=flagged_by_sku.get(key, Decimal("0.00")),
            )
        )
    return PriceAnalysis(findings=findings, skus=skus)


def _expected(baseline: Decimal, issued: date) -> Decimal:
    years = Decimal((issued - WINDOW_START).days) / Decimal(365)
    return baseline * (1 + GROWTH) ** years


def _cents(value: object) -> Decimal:
    return money(Decimal(str(round(float(value), 2))))
