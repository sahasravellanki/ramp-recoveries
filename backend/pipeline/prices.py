"""Price pass-throughs. No model is involved, and no category rate is used.

A price increase counts only when every required test passes:

- origin: the item is imported from a country with an IEEPA tariff on the invoice
- timing: the jump starts 0 to 90 days after that country's tariff date, not before
- size: the per-unit jump is no larger than tariff rate times import cost
- control: the supplier's domestic or unaffected goods did not rise by a similar amount

A price that falls back after February 20, 2026 is recorded and is not required.
The claimed amount is the difference-in-differences excess. Low is half of that.
High is the raw jump. The mock benchmark is stored and never enters a dollar.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .config import WINDOW_END, WINDOW_START
from .models import Bill, LineCategory, LineLabel, PriceAnalysis, PriceFinding, PriceTest, SkuPriceSummary, SkuTag, money
from .tariffs import DEFAULT_IMPORT_SHARE, first_ieepa_date, ieepa_rate, rate_label

# Ignore a move smaller than this when deciding that a jump started.
_JUMP = Decimal("0.005")
# A control group that rose within two points of the item is "a similar amount".
_SIMILAR = Decimal("0.02")
_TIMING_DAYS = 90
_HALF = Decimal("0.5")
# A mock benchmark, deliberately not the baseline, and never used in the claim.
BENCHMARK_FACTOR = Decimal("0.99")
# Hours and freight are not a control for a goods price.
_NOT_A_CONTROL = {"equipment_service", "freight_and_fees"}


@dataclass
class Observation:
    vendor: str
    sku: str
    invoice_number: str
    line_index: int
    issued: date
    description: str
    quantity: Decimal
    unit_price: Decimal
    country: str | None
    hts: str | None
    origin_inferred: bool
    import_cost_share: Decimal
    category_id: str | None
    labeled_by: str


def analyze(
    bills: list[Bill],
    labels: list[LineLabel],
    tags: dict[tuple[str, str], SkuTag],
) -> PriceAnalysis:
    label_of = {(label.invoice_number, label.line_index): label for label in labels}
    rows: list[Observation] = []
    for bill in bills:
        for line in bill.line_items:
            label = label_of.get((bill.invoice_number, line.line_index))
            if label is None or label.category is not LineCategory.product:
                continue
            tag = tags.get((bill.vendor.name, line.sku))
            rows.append(
                Observation(
                    vendor=bill.vendor.name,
                    sku=line.sku,
                    invoice_number=bill.invoice_number,
                    line_index=line.line_index,
                    issued=bill.issued_at,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    country=tag.country_of_origin if tag else None,
                    hts=tag.hts_chapter if tag else None,
                    origin_inferred=bool(tag and tag.origin_inferred),
                    import_cost_share=tag.import_cost_share if tag else DEFAULT_IMPORT_SHARE,
                    category_id=tag.category_id if tag else None,
                    labeled_by=tag.labeled_by if tag else "unlabeled",
                )
            )
    return qualify(rows)


def qualify(rows: list[Observation]) -> PriceAnalysis:
    grouped: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for row in rows:
        grouped[(row.vendor, row.sku)].append(row)

    findings: list[PriceFinding] = []
    skus: list[SkuPriceSummary] = []
    for key in sorted(grouped):
        series = sorted(grouped[key], key=lambda row: (row.issued, row.invoice_number, row.line_index))
        tests, rate, claimable = _assess(series, grouped)
        sku_findings = _findings(series, grouped, rate) if claimable else []
        findings.extend(sku_findings)
        skus.append(_summary(series, sku_findings, tests, rate))
    return PriceAnalysis(findings=findings, skus=skus)


def _summary(
    series: list[Observation],
    sku_findings: list[PriceFinding],
    tests: list[PriceTest],
    rate: Decimal | None,
) -> SkuPriceSummary:
    head = series[0]
    baseline = _baseline_price(series, first_ieepa_date(head.country))
    flagged = money(sum((item.amount for item in sku_findings), Decimal("0")))
    low = money(sum((item.low_amount for item in sku_findings), Decimal("0")))
    high = money(sum((item.high_amount for item in sku_findings), Decimal("0")))
    revert = next((test for test in tests if test.id == "revert"), None)
    fell_back = None if revert is None or "No invoice after" in revert.detail else revert.passed
    return SkuPriceSummary(
        vendor_name=head.vendor,
        sku=head.sku,
        baseline=baseline,
        observations=len(series),
        benchmark_price=money(baseline * BENCHMARK_FACTOR) if baseline is not None else None,
        fell_back_after_window=fell_back if sku_findings else None,
        flagged_amount=flagged,
        tests=tests,
        country=head.country,
        hts_chapter=head.hts,
        origin_inferred=head.origin_inferred,
        tariff_rate=rate,
        qualified=bool(sku_findings),
        claim_low=low,
        claim_expected=flagged,
        claim_high=high,
    )


def _findings(
    series: list[Observation], grouped: dict[tuple[str, str], list[Observation]], rate: Decimal | None
) -> list[PriceFinding]:
    head = series[0]
    tariff_on = first_ieepa_date(head.country)
    baseline = _baseline_price(series, tariff_on)
    jump = _jump_date(series, baseline)
    control = _control_percent(head, series, grouped)
    if baseline is None or jump is None or control is None:
        return []
    out: list[PriceFinding] = []
    for row in series:
        if not (WINDOW_START <= row.issued <= WINDOW_END) or row.issued < jump:
            continue
        if ieepa_rate(row.country, row.issued) <= 0 or row.unit_price <= baseline:
            continue
        low, expected, high, did_per, raw_per = _line_amounts(baseline, row.unit_price, control, row.quantity)
        if expected <= 0:
            continue
        out.append(
            PriceFinding(
                vendor_name=row.vendor,
                sku=row.sku,
                invoice_number=row.invoice_number,
                line_index=row.line_index,
                issued_at=row.issued,
                description=row.description,
                quantity=row.quantity,
                unit_price=row.unit_price,
                baseline=baseline,
                expected=money(baseline * (1 + control)),
                excess_per_unit=money(raw_per),
                capped_per_unit=money(did_per),
                amount=expected,
                category_id=row.category_id or "",
                tariff_rate=rate or Decimal("0"),
                labeled_by=row.labeled_by,
                low_amount=low,
                high_amount=high,
                origin_inferred=row.origin_inferred,
                country=row.country,
                hts_chapter=row.hts,
            )
        )
    return out


def _assess(
    series: list[Observation], grouped: dict[tuple[str, str], list[Observation]]
) -> tuple[list[PriceTest], Decimal | None, bool]:
    head = series[0]
    country = head.country
    tariff_on = first_ieepa_date(country)
    baseline = _baseline_price(series, tariff_on)
    jump = _jump_date(series, baseline) if baseline is not None else None
    rate = ieepa_rate(country, jump) if jump is not None else Decimal("0")
    share = head.import_cost_share or DEFAULT_IMPORT_SHARE

    origin_ok = bool(country) and country != "US" and jump is not None and rate > 0 and _lines_have_a_tariff(series, jump)
    if not country or country == "US":
        origin_detail = "Domestic, or no country of origin. No IEEPA tariff applies."
    elif jump is None:
        origin_detail = f"{country} is the origin. The unit price never moved off its pre-tariff price."
    elif rate <= 0:
        origin_detail = f"{country} had no IEEPA tariff in effect on {jump.isoformat()}, when the price moved."
    else:
        origin_detail = rate_label(country, jump)
        if head.origin_inferred:
            origin_detail += " Origin was inferred, not printed on the invoice."

    if tariff_on is None or jump is None:
        timing_ok = False
        timing_detail = "No tariff date, or no price jump, so timing cannot pass."
    else:
        last = tariff_on + timedelta(days=_TIMING_DAYS)
        timing_ok = tariff_on <= jump <= last
        gap = (jump - tariff_on).days
        if jump < tariff_on:
            timing_detail = f"The price moved on {jump.isoformat()}, before {country}'s tariff date {tariff_on.isoformat()}."
        elif jump > last:
            timing_detail = f"The price moved on {jump.isoformat()}, {gap} days after {tariff_on.isoformat()}. The window is 0 to {_TIMING_DAYS} days."
        else:
            timing_detail = f"The price moved on {jump.isoformat()}, {gap} days after {country}'s tariff date {tariff_on.isoformat()}."

    if baseline is None or jump is None or rate <= 0:
        size_ok = False
        size_detail = "No baseline and in-force tariff rate to compare the jump with."
    else:
        biggest = _max_jump(series, baseline, jump)
        cap = rate * share * baseline
        size_ok = biggest <= cap + Decimal("0.005")
        size_detail = (
            f"Largest per-unit jump is ${biggest:,.2f}. The cap is {rate * 100:.0f}% × {share * 100:.0f}% import share × ${baseline:,.2f} = ${cap:,.2f}."
        )

    control = _control_percent(head, series, grouped)
    item_pct = ((series_price_on(series, jump) - baseline) / baseline) if baseline and jump else None
    if control is None or item_pct is None:
        control_ok = False
        control_detail = "No domestic or unaffected item from this supplier to compare against."
    else:
        gap = item_pct - control
        control_ok = gap > _SIMILAR
        control_detail = (
            f"This item rose {item_pct * 100:.1f}%. The supplier's other unaffected goods rose {control * 100:.1f}% in the same period. "
            f"The difference is {gap * 100:.1f} points."
        )

    fell = _fell_back(series, baseline) if baseline is not None else None
    if fell is None:
        revert_detail = "No invoice after February 20, 2026 to check."
        revert_ok = False
    elif fell:
        revert_detail = "After February 20, 2026 the price came back near the pre-tariff price."
        revert_ok = True
    else:
        revert_detail = "After February 20, 2026 the price was still up."
        revert_ok = False

    tests = [
        PriceTest(id="origin", name="Imported, tariff in effect", passed=origin_ok, required=True, detail=origin_detail),
        PriceTest(id="timing", name="Jump within 90 days of the tariff date", passed=timing_ok, required=True, detail=timing_detail),
        PriceTest(id="size", name="Jump no larger than the tariff on import cost", passed=size_ok, required=True, detail=size_detail),
        PriceTest(id="control", name="Not matched by unaffected goods", passed=control_ok, required=True, detail=control_detail),
        PriceTest(id="revert", name="Price fell back after the window", passed=revert_ok, required=False, detail=revert_detail),
    ]
    required_ok = all(test.passed for test in tests if test.required)
    return tests, rate if rate > 0 else None, required_ok and bool(claim_lines_exist(series, baseline, jump, control))


def claim_lines_exist(series, baseline, jump, control) -> bool:
    if baseline is None or jump is None or control is None:
        return False
    for row in series:
        if WINDOW_START <= row.issued <= WINDOW_END and row.issued >= jump and row.unit_price > baseline:
            _, expected, _, _, _ = _line_amounts(baseline, row.unit_price, control, row.quantity)
            if expected > 0 and ieepa_rate(row.country, row.issued) > 0:
                return True
    return False


def _line_amounts(baseline: Decimal, unit: Decimal, control_pct: Decimal, qty: Decimal):
    raw_per = unit - baseline
    did_per = raw_per - (control_pct * baseline)
    if did_per < 0:
        did_per = Decimal("0")
    low = money(did_per * _HALF * qty)
    expected = money(did_per * qty)
    high = money(raw_per * qty)
    return low, expected, high, did_per, raw_per


def _baseline_price(series: list[Observation], tariff_on: date | None) -> Decimal | None:
    cutoff = tariff_on or WINDOW_START
    prior = [row.unit_price for row in series if row.issued < cutoff]
    if not prior:
        return None
    return _median(prior)


def _jump_date(series: list[Observation], baseline: Decimal | None) -> date | None:
    if baseline is None:
        return None
    bar = baseline * (1 + _JUMP)
    for row in series:
        if row.unit_price > bar:
            return row.issued
    return None


def series_price_on(series: list[Observation], jump: date | None) -> Decimal:
    if jump is None:
        return series[0].unit_price
    for row in series:
        if row.issued == jump and row.unit_price > 0:
            return row.unit_price
    return series[-1].unit_price


def _max_jump(series: list[Observation], baseline: Decimal, jump: date) -> Decimal:
    jumps = [
        row.unit_price - baseline
        for row in series
        if WINDOW_START <= row.issued <= WINDOW_END and row.issued >= jump
    ]
    return max(jumps) if jumps else Decimal("0")


def _lines_have_a_tariff(series: list[Observation], jump: date) -> bool:
    return any(
        WINDOW_START <= row.issued <= WINDOW_END and row.issued >= jump and ieepa_rate(row.country, row.issued) > 0
        for row in series
    )


def _control_percent(
    head: Observation, series: list[Observation], grouped: dict[tuple[str, str], list[Observation]]
) -> Decimal | None:
    tariff_on = first_ieepa_date(head.country)
    baseline = _baseline_price(series, tariff_on)
    jump = _jump_date(series, baseline) if baseline is not None else None
    if jump is None:
        return None
    percents: list[Decimal] = []
    for (vendor, sku), other in grouped.items():
        if vendor != head.vendor or sku == head.sku:
            continue
        sample = other[0]
        if sample.category_id in _NOT_A_CONTROL:
            continue
        if not _unaffected(sample.country, jump):
            continue
        ordered = sorted(other, key=lambda row: row.issued)
        base = _baseline_price(ordered, tariff_on)
        during = [row.unit_price for row in ordered if jump <= row.issued <= WINDOW_END]
        if base is None or base <= 0 or not during:
            continue
        percents.append((_median(during) - base) / base)
    if not percents:
        return None
    return _median(percents)


def _unaffected(country: str | None, day: date) -> bool:
    if country is None:
        return False
    if country == "US":
        return True
    return ieepa_rate(country, day) <= 0


def _fell_back(series: list[Observation], baseline: Decimal | None) -> bool | None:
    if baseline is None:
        return None
    after = [row.unit_price for row in series if row.issued > WINDOW_END]
    if not after:
        return None
    return _median(after) <= baseline * (1 + _SIMILAR)


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
