"""Price pass-throughs. No model is involved, and no category rate is used.

A price increase counts only when every required test passes:

- origin: the item is imported from a country with an IEEPA tariff on the invoice
- timing: the jump starts 0 to 90 days after any IEEPA rate increase for that country
- size: the per-unit jump is no larger than tariff rate times import cost
- control: unaffected goods did not rise by a similar amount

The control group is the same supplier's domestic or unaffected items. If that
supplier has none, it is the same category from other suppliers. If no control
exists, the test is Needs review and the item is not claimed.

A price that falls back after February 20, 2026 is recorded and is not required.
The claimed amount is the difference-in-differences excess. Low is half of that.
High is the raw jump. The mock benchmark is stored and never enters a dollar.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .claims import _strength, _tier
from .config import WINDOW_END, WINDOW_START
from .models import (
    LineCategory,
    LineLabel,
    PriceAnalysis,
    PriceFinding,
    PriceTest,
    SkuPriceSummary,
    SkuTag,
    money,
)
from .tariffs import (
    DEFAULT_IMPORT_SHARE,
    first_ieepa_date,
    ieepa_rate,
    increase_label,
    match_increase,
    rate_increases,
    rate_label,
)

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
_SIZE_NAME = "Jump no larger than the tariff on import cost"


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


@dataclass
class _ControlMatch:
    percent: Decimal | None
    source: str
    vendors: list[str]


@dataclass
class _Assessment:
    tests: list[PriceTest]
    rate: Decimal | None
    claimable: bool
    baseline: Decimal | None
    jump: date | None
    control: Decimal | None
    share: Decimal
    max_jump: Decimal
    needs_review: bool
    matched_action: str | None


def analyze(
    bills: list,
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
        assessment = _assess(series, grouped)
        sku_findings = _findings(series, assessment) if assessment.claimable else []
        findings.extend(sku_findings)
        skus.append(_summary(series, sku_findings, assessment))
    return PriceAnalysis(findings=findings, skus=skus)


def _summary(series: list[Observation], sku_findings: list[PriceFinding], assessment: _Assessment) -> SkuPriceSummary:
    head = series[0]
    baseline = assessment.baseline
    flagged = money(sum((item.amount for item in sku_findings), Decimal("0")))
    low = money(sum((item.low_amount for item in sku_findings), Decimal("0")))
    high = money(sum((item.high_amount for item in sku_findings), Decimal("0")))
    revert = next((test for test in assessment.tests if test.id == "revert"), None)
    fell_back = None if revert is None or "No invoice after" in revert.detail else revert.passed
    return SkuPriceSummary(
        vendor_name=head.vendor,
        sku=head.sku,
        baseline=baseline,
        observations=len(series),
        benchmark_price=money(baseline * BENCHMARK_FACTOR) if baseline is not None else None,
        fell_back_after_window=fell_back,
        flagged_amount=flagged,
        tests=assessment.tests,
        country=head.country,
        hts_chapter=head.hts,
        origin_inferred=head.origin_inferred,
        tariff_rate=assessment.rate,
        qualified=bool(sku_findings),
        needs_review=assessment.needs_review,
        claim_low=low,
        claim_expected=flagged,
        claim_high=high,
        import_cost_share=assessment.share,
        max_unit_jump=assessment.max_jump,
        control_percent=assessment.control,
        jump_on=assessment.jump,
        matched_action=assessment.matched_action,
        labeled_by=head.labeled_by,
    )


def _findings(series: list[Observation], assessment: _Assessment) -> list[PriceFinding]:
    baseline = assessment.baseline
    jump = assessment.jump
    control = assessment.control
    rate = assessment.rate
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


def _assess(series: list[Observation], grouped: dict[tuple[str, str], list[Observation]]) -> _Assessment:
    head = series[0]
    country = head.country
    tariff_on = first_ieepa_date(country)
    baseline = _baseline_price(series, tariff_on)
    jump = _jump_date(series, baseline) if baseline is not None else None
    rate = ieepa_rate(country, jump) if jump is not None else Decimal("0")
    share = head.import_cost_share or DEFAULT_IMPORT_SHARE
    matched = match_increase(country, jump, window_days=_TIMING_DAYS) if jump is not None and country else None
    matched_action = increase_label(matched) if matched is not None else None

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

    if jump is None or not country or country == "US":
        timing_ok = False
        timing_detail = "No price jump, or no foreign origin, so timing cannot pass."
    elif matched is None:
        timing_ok = False
        known = rate_increases(country)
        if not known:
            timing_detail = f"{country} has no IEEPA rate increase to time the jump against."
        elif jump < known[0].effective:
            timing_detail = (
                f"The price moved on {jump.isoformat()}, before {country}'s first IEEPA rate increase "
                f"on {known[0].effective.isoformat()}."
            )
        else:
            timing_detail = (
                f"The price moved on {jump.isoformat()}, which is not within 0 to {_TIMING_DAYS} days after an IEEPA "
                f"rate increase for {country}. The latest increase is {increase_label(known[-1])}."
            )
    else:
        timing_ok = True
        gap = (jump - matched.effective).days
        timing_detail = f"The price moved on {jump.isoformat()}, {gap} days after {matched_action}."

    biggest = _max_jump(series, baseline, jump) if baseline is not None and jump is not None else Decimal("0")
    size = size_test(baseline, rate if rate > 0 else None, biggest, share)

    imported_jump = bool(country) and country != "US" and jump is not None and rate > 0
    if not imported_jump:
        control_match = _ControlMatch(None, "skipped", [])
        if jump is None:
            control_detail = "The unit price never moved off its earlier price, so there is no increase to compare."
        else:
            control_detail = "This is not an imported item with an IEEPA tariff in effect, so the control test does not apply."
        control_status = "fail"
        control = None
    else:
        control_match = _control_match(head, grouped, tariff_on, jump)
        control = control_match.percent
        item_pct = ((series_price_on(series, jump) - baseline) / baseline) if baseline and jump else None
        if control_match.source in {"none", "uncategorized"} or control is None or item_pct is None:
            control_status = "needs_review"
            control = None
            if control_match.source == "uncategorized":
                control_detail = (
                    "This supplier has no domestic or unaffected item, and this item has no category to compare "
                    "across suppliers. Needs review."
                )
            else:
                control_detail = (
                    "This supplier has no domestic or unaffected item, and no other supplier has an unaffected item "
                    "in this category. Needs review."
                )
        else:
            gap = item_pct - control
            control_status = "pass" if gap > _SIMILAR else "fail"
            movement = (
                f"This item rose {_pct(item_pct)}. The comparison group rose {_pct(control)} in the same period. "
                f"The difference is {gap * 100:.1f} points."
            )
            if control_match.source == "supplier":
                control_detail = f"{movement} The comparison is this supplier's other unaffected goods."
            else:
                names = _name_list(control_match.vendors)
                control_detail = (
                    "This supplier has no domestic or unaffected item. Unaffected goods in the same category from "
                    f"other suppliers ({names}) are the comparison. {movement}"
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
        PriceTest(
            id="origin",
            name="Imported, tariff in effect",
            passed=origin_ok,
            required=True,
            detail=origin_detail,
            status="pass" if origin_ok else "fail",
        ),
        PriceTest(
            id="timing",
            name="Jump within 90 days of a rate increase",
            passed=timing_ok,
            required=True,
            detail=timing_detail,
            status="pass" if timing_ok else "fail",
            matched_action=matched_action,
        ),
        size,
        PriceTest(
            id="control",
            name="Not matched by unaffected goods",
            passed=control_status == "pass",
            required=True,
            detail=control_detail,
            status=control_status,
        ),
        PriceTest(
            id="revert",
            name="Price fell back after the window",
            passed=revert_ok,
            required=False,
            detail=revert_detail,
            status="pass" if revert_ok else "fail",
        ),
    ]
    required_ok = all(test.status == "pass" for test in tests if test.required)
    others_ok = all(test.status == "pass" for test in tests if test.required and test.id != "control")
    needs_review = control_status == "needs_review" and others_ok
    claimable = required_ok and claim_lines_exist(series, baseline, jump, control)
    return _Assessment(
        tests=tests,
        rate=rate if rate > 0 else None,
        claimable=claimable,
        baseline=baseline,
        jump=jump,
        control=control,
        share=share,
        max_jump=biggest,
        needs_review=needs_review,
        matched_action=matched_action,
    )


def size_test(baseline: Decimal | None, rate: Decimal | None, biggest: Decimal, share: Decimal) -> PriceTest:
    if baseline is None or rate is None or rate <= 0:
        return PriceTest(
            id="size",
            name=_SIZE_NAME,
            passed=False,
            required=True,
            detail="No baseline and in-force tariff rate to compare the jump with.",
            status="fail",
        )
    cap = rate * share * baseline
    ok = biggest <= cap + Decimal("0.005")
    detail = (
        f"Largest per-unit jump is ${biggest:,.2f}. Assumes import cost is {_pct(share)} of price. "
        f"The cap is {rate * 100:.0f}% × {_pct(share)} × ${baseline:,.2f} = ${cap:,.2f}."
    )
    return PriceTest(id="size", name=_SIZE_NAME, passed=ok, required=True, detail=detail, status="pass" if ok else "fail")


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


def _control_match(
    head: Observation,
    grouped: dict[tuple[str, str], list[Observation]],
    tariff_on: date | None,
    jump: date,
) -> _ControlMatch:
    own = _peer_changes(head, grouped, tariff_on, jump, same_vendor=True)
    if own:
        return _ControlMatch(_median([pct for _, pct in own]), "supplier", _unique([vendor for vendor, _ in own]))
    if not head.category_id or head.category_id in _NOT_A_CONTROL:
        return _ControlMatch(None, "uncategorized", [])
    peers = _peer_changes(head, grouped, tariff_on, jump, same_vendor=False)
    if not peers:
        return _ControlMatch(None, "none", [])
    return _ControlMatch(_median([pct for _, pct in peers]), "category", _unique([vendor for vendor, _ in peers]))


def _peer_changes(
    head: Observation,
    grouped: dict[tuple[str, str], list[Observation]],
    tariff_on: date | None,
    jump: date,
    *,
    same_vendor: bool,
) -> list[tuple[str, Decimal]]:
    found: list[tuple[str, Decimal]] = []
    for (vendor, sku), other in grouped.items():
        if vendor == head.vendor and sku == head.sku:
            continue
        if same_vendor and vendor != head.vendor:
            continue
        if not same_vendor and vendor == head.vendor:
            continue
        sample = other[0]
        if sample.category_id in _NOT_A_CONTROL:
            continue
        if not same_vendor and sample.category_id != head.category_id:
            continue
        if not _unaffected(sample.country, jump):
            continue
        ordered = sorted(other, key=lambda row: row.issued)
        base = _baseline_price(ordered, tariff_on)
        during = [row.unit_price for row in ordered if jump <= row.issued <= WINDOW_END]
        if base is None or base <= 0 or not during:
            continue
        found.append((vendor, (_median(during) - base) / base))
    return found


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


def _pct(value: Decimal) -> str:
    points = value * 100
    if points == points.to_integral_value():
        return f"{points:.0f}%"
    return f"{points:.1f}%"


def _unique(names: list[str]) -> list[str]:
    seen: list[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen


def _name_list(names: list[str]) -> str:
    shown = names[:4]
    extra = len(names) - len(shown)
    text = ", ".join(shown)
    if extra > 0:
        text += f", and {extra} more"
    return text or "other suppliers"


def recalculate_share(
    history: dict,
    share: Decimal,
    *,
    ieepa: Decimal,
    credits: Decimal,
    non_refundable: Decimal,
    clause: bool,
) -> dict:
    """Re-run the size test at a new import-cost share and rebuild the claim dollars.

    Origin, timing, and control stay as they were. Only the size gate moves.
    """
    share = Decimal(share)
    math_rows = history.get("math") or []
    display = {sku["sku"]: dict(sku) for sku in history.get("skus") or []}
    price_low = Decimal("0")
    price_expected = Decimal("0")
    price_high = Decimal("0")
    lines: list[dict] = []
    reverted_known: list[bool] = []
    qualified_inferred: list[bool] = []
    updated_skus: list[dict] = []
    review_blocked = False

    for row in math_rows:
        tests, low, expected, high, row_lines, qualified = _reprice_sku(row, share)
        sku = display.get(row["sku"], {"sku": row["sku"], "description": row.get("description", "")})
        sku["tests"] = tests
        sku["claim_low"] = _num(low)
        sku["claim_expected"] = _num(expected)
        sku["claim_high"] = _num(high)
        sku["conservative_increase"] = _num(expected)
        sku["raw_increase"] = _num(high)
        updated_skus.append(sku)
        if qualified:
            price_low += low
            price_expected += expected
            price_high += high
            lines.extend(row_lines)
            qualified_inferred.append(bool(row.get("origin_inferred")))
            if row.get("fell_back") is not None:
                reverted_known.append(bool(row["fell_back"]))
        control = next((test for test in tests if test["id"] == "control"), None)
        others = [test for test in tests if test.get("required") and test["id"] != "control"]
        if control and control["status"] == "needs_review" and all(test["status"] == "pass" for test in others):
            review_blocked = True

    price_low, price_expected, price_high = money(price_low), money(price_expected), money(price_high)
    gross = money(ieepa + price_expected)
    refundable = money(gross - credits)
    explicit = ieepa > 0
    has_price = price_expected > 0
    inferred_only = has_price and ieepa <= 0 and bool(qualified_inferred) and all(qualified_inferred)
    tier, reasons = _tier(explicit, clause, has_price, inferred_only)
    if tier is None and review_blocked:
        reasons = [
            "The price increase lines up with an IEEPA rate increase, but there is no control group to compare it with.",
            "It needs a person to review it, so nothing is claimed yet.",
        ]
    elif tier is None and math_rows and not explicit:
        reasons = [
            "At this import-cost share, the price increase is larger than the tariff on the import cost, so it is not claimed."
        ]
    reverted = all(reverted_known) if reverted_known else None
    strength = _strength(gross, non_refundable, tier, clause, reverted, inferred_only)
    next_history = dict(history)
    next_history["skus"] = updated_skus
    next_history["import_cost_share"] = float(share)
    next_history["claim_low"] = _num(price_low) if has_price else None
    next_history["claim_expected"] = _num(price_expected) if has_price else None
    next_history["claim_high"] = _num(price_high) if has_price else None
    next_history["raw_price_increase"] = _num(price_high)
    next_history["conservative_price_increase"] = _num(price_expected)
    next_history["evidence_tier"] = tier
    next_history["tier_reasons"] = reasons
    next_history["origin_inferred_only"] = inferred_only
    return {
        "history": next_history,
        "price_excess": price_expected,
        "raw": price_high,
        "gross": gross,
        "refundable": refundable,
        "lines": lines,
        "reverted": reverted,
        "tier": tier,
        "reasons": reasons,
        "inferred_only": inferred_only,
        "strength": strength,
    }


def _reprice_sku(row: dict, share: Decimal):
    baseline = Decimal(str(row["baseline"])) if row.get("baseline") is not None else None
    rate = Decimal(str(row["tariff_rate"])) if row.get("tariff_rate") not in (None, "") else None
    biggest = Decimal(str(row.get("max_unit_jump") or "0"))
    control = Decimal(str(row["control_percent"])) if row.get("control_percent") not in (None, "") else None
    fresh = size_test(baseline, rate, biggest, share).model_dump()
    tests = [fresh if test["id"] == "size" else test for test in row.get("tests") or []]
    if not any(test["id"] == "size" for test in tests):
        tests.append(fresh)
    required_ok = all(test["status"] == "pass" for test in tests if test.get("required"))
    low = expected = high = Decimal("0")
    lines: list[dict] = []
    if required_ok and baseline is not None and control is not None:
        for line in row.get("lines") or []:
            qty = Decimal(str(line["quantity"]))
            unit = Decimal(str(line["unit_price"]))
            lo, ex, hi, _, _ = _line_amounts(baseline, unit, control, qty)
            if ex <= 0:
                continue
            low += lo
            expected += ex
            high += hi
            lines.append({**line, "amount": ex})
        low, expected, high = money(low), money(expected), money(high)
    return tests, low, expected, high, lines, bool(lines)


def _num(value: Decimal) -> float:
    return float(money(value))
