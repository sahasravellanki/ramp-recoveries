"""Run the pipeline end to end and compare it to the labeled ground truth.

    cd backend && python -m pipeline.run
"""

from __future__ import annotations

import json
from decimal import Decimal

from .claims import build as build_claims
from .classify import classify_bills
from .config import get_settings
from .contracts import analyze as analyze_contracts
from .exposure import tag_skus
from .importer import find_cases
from .letters import draft_all
from .models import Decision, Usage, VendorClaim, money
from .prices import analyze as analyze_prices
from .sources import MockBillPaySource

EXACT = Decimal("0.05")


def main() -> None:
    settings = get_settings()
    usage = Usage()
    data_dir = settings.resolved_data_dir()
    source = MockBillPaySource(data_dir)

    bills = source.get_bills()
    vendors = source.get_vendors()
    credits = source.get_vendor_credits()

    labels = classify_bills(bills, settings, usage)
    tags = tag_skus(bills, settings, usage)
    prices = analyze_prices(bills, labels, tags)
    importer_cases = find_cases(bills, labels)
    contracts = analyze_contracts(vendors, data_dir, settings, usage)
    claims = build_claims(bills, vendors, labels, prices, credits, contracts, importer_cases)
    letters = draft_all(claims, settings, usage)

    ground_truth = json.loads((data_dir / "ground_truth.json").read_text())
    _print_report(settings, bills, labels, prices, importer_cases, claims, letters, usage, ground_truth)
    _check(claims, importer_cases, ground_truth)


def _print_report(settings, bills, labels, prices, importer_cases, claims, letters, usage, ground_truth) -> None:
    mode = f"DEMO ({settings.demo_reason})" if settings.use_demo else "LIVE"
    math_failures = sum(1 for bill in bills if bill.math and bill.math.failed)
    review = [label for label in labels if label.decision is Decision.needs_review]
    escalated = sum(1 for label in labels if label.escalated)
    print(f"Ramp Recoveries pipeline  [{mode}]")
    print(f"tier 1 model: {settings.tier1_model}    tier 2 model: {settings.tier2_model}")
    print(f"bills {len(bills)}   lines {len(labels)}   escalated {escalated}   needs review {len(review)}   math failures {math_failures}")
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
    print("Ground truth comparison  (gross is before credits; refundable is after)")
    comp = f"{'Vendor':34} {'Our gross':>12} {'GT gross':>12} {'Delta':>10} {'Our nonref':>12} {'GT nonref':>12} {'Net vs GT':>10}"
    print(comp)
    print("-" * len(comp))
    ours = {claim.vendor_name: claim for claim in claims}
    for name, truth in ground_truth["suppliers"].items():
        claim = ours[name]
        gt_gross = _dollars(truth["refundable_claim_total"])
        gt_non = _dollars(truth["non_refundable_total"])
        gt_net = _dollars(truth["net_claim_total"])
        gross_delta = claim.gross_refundable - gt_gross
        net_delta = claim.refundable_total - gt_net
        print(
            f"{name:34} {claim.gross_refundable:12,.2f} {gt_gross:12,.2f} {gross_delta:10,.2f} "
            f"{claim.non_refundable_total:12,.2f} {gt_non:12,.2f} {net_delta:10,.2f}"
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
    print("Model usage")
    for model in sorted(usage.calls):
        print(f"  {model:20} calls {usage.calls[model]:4}   in {usage.input_tokens.get(model, 0)} tok   out {usage.output_tokens.get(model, 0)} tok")
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


def _check(claims: list[VendorClaim], importer_cases, ground_truth) -> None:
    """Surcharge vendors and the importer cases should match to the cent. Price claims will not."""
    by_name = {claim.vendor_name: claim for claim in claims}
    problems = []
    for name, truth in ground_truth["suppliers"].items():
        claim = by_name[name]
        gt_non = _dollars(truth["non_refundable_total"])
        if abs(claim.non_refundable_total - gt_non) > EXACT:
            problems.append(f"{name} non-refundable {claim.non_refundable_total} vs {gt_non}")
        # Explicit-surcharge vendors carry no price component, so the gross should match.
        if truth["basis"] == "explicit_surcharge":
            gt_gross = _dollars(truth["refundable_claim_total"])
            if abs(claim.gross_refundable - gt_gross) > EXACT:
                problems.append(f"{name} gross {claim.gross_refundable} vs {gt_gross}")
        if truth["basis"] == "none" and claim.gross_refundable != 0:
            problems.append(f"{name} expected no claim, got {claim.gross_refundable}")
    gt_cases = {case["invoice_number"]: _dollars(case["customs_duty_paid"]) for case in ground_truth["importer_of_record_cases"]}
    found = {case.invoice_number: case.amount for case in importer_cases}
    if set(found) != set(gt_cases):
        problems.append(f"importer invoices {sorted(found)} vs {sorted(gt_cases)}")
    for number, amount in gt_cases.items():
        if number in found and abs(found[number] - amount) > EXACT:
            problems.append(f"{number} duty {found[number]} vs {amount}")
    if problems:
        print("CHECK FAILED")
        for problem in problems:
            print(f"  {problem}")
        raise SystemExit(1)
    print("Check passed: explicit-surcharge totals, non-refundable totals, and importer cases match ground truth.")


def _dollars(value: object) -> Decimal:
    return money(Decimal(str(round(float(value), 2))))


if __name__ == "__main__":
    main()
