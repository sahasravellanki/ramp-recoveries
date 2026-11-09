"""Run the pipeline end to end and compare it to the labeled ground truth.

    cd backend && python -m pipeline.run
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from decimal import Decimal

from .claims import build as build_claims
from .classify import classify_bills
from .config import get_settings
from .contracts import analyze as analyze_contracts
from .exposure import tag_skus
from .importer import find_cases
from .letters import draft_all
from .models import Decision, LineLabel, Usage, VendorClaim, money
from .prices import analyze as analyze_prices
from .sources import MockBillPaySource

EXACT = Decimal("0.05")

# Standard rates, USD per million tokens. Cache rates apply only when the API reports them.
# https://platform.claude.com/docs/en/about-claude/pricing
RATES = {
    "claude-haiku-4-5": {"input": Decimal("1"), "cache_write": Decimal("1.25"), "cache_read": Decimal("0.10"), "output": Decimal("5")},
    "claude-sonnet-4-5": {"input": Decimal("3"), "cache_write": Decimal("3.75"), "cache_read": Decimal("0.30"), "output": Decimal("15")},
}

SCORING_RULES = """
Strength, first match wins:
  High     a refund or pass-through clause, AND (an explicit IEEPA surcharge OR a price increase that reverted after the window)
  Medium   an explicit IEEPA surcharge, OR a reverted price increase, with no clause
  Low      the only evidence is a price increase that did not revert, or that no later invoice could confirm
  Tracked  nothing refundable, but non-refundable tariff lines worth watching (Section 301)
  -        nothing to claim or track
""".strip()


@dataclass
class PipelineOutput:
    labels: list
    claims: list
    letters: list
    importer_cases: list
    prices: object
    contracts: dict
    usage: Usage


def run_pipeline(settings, bills, vendors, credits, data_dir) -> PipelineOutput:
    """Label, price, and draft. Callers own persistence. Demo mode makes no network calls."""
    usage = Usage()
    labels = classify_bills(bills, settings, usage)
    tags = tag_skus(bills, settings, usage)
    prices = analyze_prices(bills, labels, tags)
    importer_cases = find_cases(bills, labels)
    contracts = analyze_contracts(vendors, data_dir, settings, usage)
    claims = build_claims(bills, vendors, labels, prices, credits, contracts, importer_cases)
    letters = draft_all(claims, settings, usage)
    return PipelineOutput(labels, claims, letters, importer_cases, prices, contracts, usage)


def main() -> None:
    settings = get_settings()
    data_dir = settings.resolved_data_dir()
    source = MockBillPaySource(data_dir)
    bills = source.get_bills()
    result = run_pipeline(settings, bills, source.get_vendors(), source.get_vendor_credits(), data_dir)
    ground_truth = json.loads((data_dir / "ground_truth.json").read_text())
    _print_report(
        settings, data_dir, bills, result.labels, result.prices,
        result.importer_cases, result.claims, result.letters, result.usage, ground_truth,
    )
    _check(result.claims, result.importer_cases, ground_truth, strict=settings.use_demo)


def _print_report(settings, data_dir, bills, labels, prices, importer_cases, claims, letters, usage, ground_truth) -> None:
    mode = f"DEMO ({settings.demo_reason})" if settings.use_demo else "LIVE"
    math_failures = sum(1 for bill in bills if bill.math and bill.math.failed)
    review = [label for label in labels if label.decision is Decision.needs_review]
    escalated = [label for label in labels if label.escalated]
    print(f"Ramp Recoveries pipeline  [{mode}]")
    print(f"tier 1 model: {settings.tier1_model}    tier 2 model: {settings.tier2_model}")
    print(f"bills {len(bills)}   lines {len(labels)}   math failures {math_failures}")
    print(f"tier 1 labeled on its own: {len(labels) - len(escalated)}   escalated to tier 2: {len(escalated)}   needs review: {len(review)}")
    print()
    print(SCORING_RULES)
    print()
    header = f"{'Vendor':34} {'Strength':8} {'Refundable':>12} {'Surcharge':>11} {'Price excess':>13} {'Credits':>9} {'Non-ref.':>10}"
    print(header)
    print("-" * len(header))
    for claim in claims:
        strength = claim.strength.value if claim.strength else "-"
        print(
            f"{claim.vendor_name:34} {strength:8} {claim.refundable_total:12,.2f} {claim.ieepa_surcharge_total:11,.2f} "
            f"{claim.price_excess_total:13,.2f} {claim.credits_applied:9,.2f} {claim.non_refundable_total:10,.2f}"
        )
    print()
    print("Ground truth comparison")
    print("Expected = explicit IEEPA surcharges + conservative price claim (3%/yr allowance, flag only above 5%, cap at the category rate).")
    print("Raw price increase is the full embedded jump, shown for context. It is not the target.")
    comp = f"{'Vendor':34} {'Our gross':>12} {'Expected':>12} {'Delta':>10} {'Raw price':>12} {'Our nonref':>11} {'GT nonref':>10}"
    print(comp)
    print("-" * len(comp))
    ours = {claim.vendor_name: claim for claim in claims}
    for name, truth in ground_truth["suppliers"].items():
        claim = ours[name]
        expected = _dollars(truth["refundable_claim_total"])
        raw = _dollars(truth.get("raw_price_increase", 0))
        gt_non = _dollars(truth["non_refundable_total"])
        delta = claim.gross_refundable - expected
        print(
            f"{name:34} {claim.gross_refundable:12,.2f} {expected:12,.2f} {delta:10,.2f} "
            f"{raw:12,.2f} {claim.non_refundable_total:11,.2f} {gt_non:10,.2f}"
        )
    print()
    print("Importer of record  (excluded from supplier claims; refund is from CBP)")
    gt_cases = {case["invoice_number"]: _dollars(case["customs_duty_paid"]) for case in ground_truth["importer_of_record_cases"]}
    seen = set()
    for case in importer_cases:
        expected = gt_cases.get(case.invoice_number)
        mark = "MATCH" if expected is not None and abs(case.amount - expected) <= EXACT else "DIFF"
        print(f"  {case.invoice_number}  ${case.amount:,.2f}   ground truth ${expected:,.2f}   {mark}" if expected is not None else f"  {case.invoice_number}  ${case.amount:,.2f}   not in ground truth")
        seen.add(case.invoice_number)
    for number in gt_cases:
        if number not in seen:
            print(f"  MISSING {number}  ground truth ${gt_cases[number]:,.2f}")
    print()
    flagged = [sku for sku in prices.skus if sku.flagged_amount > 0]
    reverted = sum(1 for sku in flagged if sku.fell_back_after_window)
    unknown = sum(1 for sku in flagged if sku.fell_back_after_window is None)
    print(
        f"Price check: {len(prices.findings)} lines flagged across {len(flagged)} SKUs. "
        f"{reverted} fell back to baseline after Feb 20 2026, {unknown} had no later invoice."
    )
    print("Ramp network benchmark prices are stored per SKU and marked mock. They are not used in any total.")
    print()
    _print_accuracy(data_dir, labels, bills)
    print()
    if review:
        print("Lines left as needs_review")
        described = {(bill.invoice_number, line.line_index): line.description for bill in bills for line in bill.line_items}
        for label in review:
            text = described.get((label.invoice_number, label.line_index), "")
            print(f"  {label.invoice_number} line {label.line_index}  {label.category.value:28} {label.labeled_by}  {label.reason}")
            print(f"    {text}")
    else:
        print("Lines left as needs_review: none")
    print()
    _print_usage(settings, usage)
    print()
    print(f"Letters drafted: {len(letters)}  (drafts only, nothing sent)")
    for letter in letters:
        flag = f"  FLAGGED {letter.flagged_language}" if letter.flagged_language else ""
        print(f"  {letter.vendor_name}: {letter.word_count} words, {letter.model}{flag}")
    print()
    for letter in letters:
        print("=" * 72)
        print(letter.body)
        print()


def _print_accuracy(data_dir, labels: list[LineLabel], bills) -> None:
    path = data_dir / "labels.csv"
    if not path.exists():
        print("Label accuracy: labels.csv not found")
        return
    known = {(bill.invoice_number, line.line_index) for bill in bills for line in bill.line_items}
    ours = {(label.invoice_number, label.line_index): label for label in labels}
    compared = correct = skipped = 0
    mismatches = []
    with path.open() as fh:
        for row in csv.DictReader(fh):
            key = (row["invoice_number"], int(row["line_index"]))
            if key not in known:
                skipped += 1
                continue
            compared += 1
            got = ours[key].category.value
            if got == row["category"]:
                correct += 1
            else:
                mismatches.append((row["invoice_number"], int(row["line_index"]), row["description"], row["category"], got))
    rate = (correct / compared * 100) if compared else 0
    print(f"Label accuracy vs labels.csv: {correct}/{compared} ({rate:.1f}%). {skipped} rows skipped (credit memo, not a bill).")
    for invoice, index, description, expected, got in mismatches:
        print(f"  {invoice} line {index}  expected {expected:28} got {got:28} {description[:70]}")


def _print_usage(settings, usage: Usage) -> None:
    print("Model usage and estimated cost")
    print("Rates: Haiku 4.5 $1 / $5 per MTok, Sonnet 4.5 $3 / $15 per MTok. Cache tokens use the published 5-minute write and read rates when the API reports them.")
    total = Decimal("0")
    tiers = (("tier 1", settings.tier1_model), ("tier 2", settings.tier2_model))
    shown = set()
    for tier_name, model in tiers:
        cost = _model_cost(model, usage)
        total += cost
        shown.add(model)
        print(
            f"  {tier_name} {model:22} calls {usage.calls.get(model, 0):4}   "
            f"in {usage.input_tokens.get(model, 0):8}   out {usage.output_tokens.get(model, 0):7}   "
            f"cache r/w {usage.cache_read_tokens.get(model, 0)}/{usage.cache_write_tokens.get(model, 0)}   "
            f"est ${cost:.4f}"
        )
    for model in sorted(usage.calls):
        if model in shown:
            continue
        cost = _model_cost(model, usage)
        total += cost
        print(
            f"  {'other':6} {model:22} calls {usage.calls.get(model, 0):4}   "
            f"in {usage.input_tokens.get(model, 0):8}   out {usage.output_tokens.get(model, 0):7}   est ${cost:.4f}"
        )
    print(f"  estimated total ${total:.4f}")


def _model_cost(model: str, usage: Usage) -> Decimal:
    rate = RATES.get(model)
    if rate is None:
        return Decimal("0")
    million = Decimal(1_000_000)
    return (
        Decimal(usage.input_tokens.get(model, 0)) * rate["input"]
        + Decimal(usage.cache_write_tokens.get(model, 0)) * rate["cache_write"]
        + Decimal(usage.cache_read_tokens.get(model, 0)) * rate["cache_read"]
        + Decimal(usage.output_tokens.get(model, 0)) * rate["output"]
    ) / million


def _check(claims: list[VendorClaim], importer_cases, ground_truth, strict: bool) -> None:
    """Expected claim is the conservative number. Demo mode fails the process when it misses."""
    by_name = {claim.vendor_name: claim for claim in claims}
    problems = []
    for name, truth in ground_truth["suppliers"].items():
        claim = by_name[name]
        expected = _dollars(truth["refundable_claim_total"])
        gt_non = _dollars(truth["non_refundable_total"])
        if abs(claim.gross_refundable - expected) > EXACT:
            problems.append(f"{name} gross {claim.gross_refundable} vs expected {expected}")
        if abs(claim.non_refundable_total - gt_non) > EXACT:
            problems.append(f"{name} non-refundable {claim.non_refundable_total} vs {gt_non}")
    gt_cases = {case["invoice_number"]: _dollars(case["customs_duty_paid"]) for case in ground_truth["importer_of_record_cases"]}
    found = {case.invoice_number: case.amount for case in importer_cases}
    if set(found) != set(gt_cases):
        problems.append(f"importer invoices {sorted(found)} vs {sorted(gt_cases)}")
    for number, amount in gt_cases.items():
        if number in found and abs(found[number] - amount) > EXACT:
            problems.append(f"{number} duty {found[number]} vs {amount}")
    if not problems:
        print("Check passed: claims match the conservative expected totals, and importer cases match.")
        return
    print("CHECK DIFFERENCES")
    for problem in problems:
        print(f"  {problem}")
    if strict:
        raise SystemExit(1)


def _dollars(value: object) -> Decimal:
    return money(Decimal(str(round(float(value), 2))))


if __name__ == "__main__":
    main()
