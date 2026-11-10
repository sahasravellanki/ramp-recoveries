"""Score the pipeline against the answer key.

Keyword rules miss the three wording traps on purpose. A live run, when a key
is set, is scored the same way against the full answer. That run writes
data/eval_results.md and data/live_results/.

    cd backend && python -m pipeline.eval
"""

from __future__ import annotations

import csv
import json
from decimal import Decimal

from .config import get_settings
from .models import money
from .run import run_pipeline
from .sources import MockBillPaySource

EXACT = Decimal("0.05")
WORDING = (
    "Q3 landed cost adjustment",
    "Supplier cost pass-through",
    "Global sourcing fee",
)


def main() -> None:
    settings = get_settings()
    demo = settings.model_copy(update={"demo_mode": True})
    demo_output, demo_bills, demo_truth, demo_dir = _report(demo, "demo")
    if not settings.anthropic_api_key.strip() or settings.demo_mode:
        print()
        print("Real-model eval was not run. ANTHROPIC_API_KEY is not set, so there is nothing to call.")
        return
    print()
    live_output, bills, truth, data_dir = _report(settings, "live")
    path = _write_summary(data_dir, truth, bills, demo_output, live_output, settings)
    _write_live_results(data_dir, live_output)
    print(f"\nWrote {path}")
    print(f"Wrote {data_dir / 'live_results'}")


def _report(settings, mode: str):
    data_dir = settings.resolved_data_dir()
    source = MockBillPaySource(data_dir)
    bills = source.get_bills()
    result = run_pipeline(settings, bills, source.get_vendors(), source.get_vendor_credits(), data_dir)
    truth = json.loads((data_dir / "ground_truth.json").read_text())

    line_scores = _line_scores(data_dir, bills, result.labels)
    price_scores = _price_scores(truth, result.prices)
    print(f"Ramp Recoveries eval  [{mode}]")
    print(
        f"Flagged lines: precision {_fmt(line_scores['precision'])}  "
        f"recall {_fmt(line_scores['recall'])}  "
        f"({line_scores['hit']} of {line_scores['truth']} true IEEPA lines, {line_scores['flagged']} flagged)"
    )
    print(
        f"Flagged price items: precision {_fmt(price_scores['precision'])}  "
        f"recall {_fmt(price_scores['recall'])}  "
        f"({price_scores['hit']} of {price_scores['truth']} true items, {price_scores['flagged']} flagged)"
    )
    if line_scores["missed"]:
        print("  Missed IEEPA lines:")
        for row in line_scores["missed"]:
            print(f"    {row}")
    if line_scores["extra"]:
        print("  Extra IEEPA lines:")
        for row in line_scores["extra"]:
            print(f"    {row}")
    if price_scores["missed"] or price_scores["extra"]:
        print(f"  Price item misses: {price_scores['missed'] or 'none'}")
        print(f"  Price item extras: {price_scores['extra'] or 'none'}")

    print()
    print("Trap cases (refundable dollars the pipeline assigned)")
    ours = {claim.vendor_name: claim for claim in result.claims}
    for case in truth["cases"]:
        claim = ours.get(case["vendor"])
        got = claim.gross_refundable if claim else Decimal("0")
        answer = _dollars(truth["suppliers"][case["vendor"]]["refundable_claim_total"])
        false_positive = got if not case["should_count"] else Decimal("0")
        missed = answer - got if case["should_count"] and got + EXACT < answer else Decimal("0")
        expect_review = bool(case.get("needs_review"))
        got_review = bool(claim and claim.needs_review)
        mark = _mark(case, got, answer, false_positive, missed, expect_review, got_review)
        print(
            f"  {case['id']:16} {case['vendor']:24} pipeline ${got:,.2f}  "
            f"answer ${answer:,.2f}  false positive ${false_positive:,.2f}  {mark}"
        )

    print()
    print("Dollar error per vendor (pipeline gross minus the full answer)")
    for name, row in truth["suppliers"].items():
        claim = ours.get(name)
        got = claim.gross_refundable if claim else Decimal("0")
        answer = _dollars(row["refundable_claim_total"])
        delta = got - answer
        print(f"  {name:34} {delta:10,.2f}   pipeline ${got:,.2f}   answer ${answer:,.2f}")
    return result, bills, truth, data_dir


def _mark(case, got, answer, false_positive, missed, expect_review, got_review) -> str:
    if false_positive > EXACT:
        return "FALSE POSITIVE"
    if expect_review and not got_review:
        return "MISSING needs review"
    if not expect_review and got_review:
        return "WRONG needs review"
    if missed > EXACT:
        return "missed"
    if case["should_count"] and abs(got - answer) > EXACT:
        return "dollar mismatch"
    if expect_review:
        return "needs review"
    return "ok"


def _write_summary(data_dir, truth, bills, demo_output, live_output, settings) -> object:
    demo_claims = {claim.vendor_name: claim for claim in demo_output.claims}
    live_claims = {claim.vendor_name: claim for claim in live_output.claims}
    lines = [
        "# Eval results",
        "",
        f"Models: tier 1 `{settings.tier1_model}`, tier 2 `{settings.tier2_model}`.",
        "Rules-only is the keyword pipeline (`DEMO_MODE=1`). The model run is the same bills with the API key set.",
        "A trap is caught when the refundable dollars match the answer key within $0.05.",
        "",
        "## Per vendor",
        "",
        "| Vendor | Expected | Model found | Rules-only found | Model error |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, row in truth["suppliers"].items():
        expected = _dollars(row["refundable_claim_total"])
        model_got = _gross(live_claims, name)
        rules_got = _gross(demo_claims, name)
        lines.append(
            f"| {name} | {_money(expected)} | {_money(model_got)} | {_money(rules_got)} | {_money(model_got - expected)} |"
        )

    expected_net = _dollars(truth["totals"]["net_claim_total_after_credits"])
    rules_net = _dollars(truth["totals"]["demo_net_claim_total_after_credits"])
    model_net = sum((claim.refundable_total for claim in live_output.claims), Decimal("0"))
    rules_found_net = sum((claim.refundable_total for claim in demo_output.claims), Decimal("0"))
    lines.extend(
        [
            "",
            "## Net refundable",
            "",
            f"Expected, after the $500 credit already on file: **{_money(expected_net)}**.",
            f"Model found: **{_money(model_net)}** (error {_money(model_net - expected_net)}).",
            f"Rules-only found: **{_money(rules_found_net)}** (answer for that mode {_money(rules_net)}).",
            "",
            "## Traps",
            "",
            "| Trap | Vendor | Should count | Expected | Rules-only | Model | Rules-only result | Model result |",
            "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for case in truth["cases"]:
        vendor = case["vendor"]
        answer = _dollars(truth["suppliers"][vendor]["refundable_claim_total"])
        target = answer if case["should_count"] else Decimal("0")
        rules_got = _gross(demo_claims, vendor)
        model_got = _gross(live_claims, vendor)
        rules_claim = demo_claims.get(vendor)
        model_claim = live_claims.get(vendor)
        lines.append(
            "| {id} | {vendor} | {count} | {expected} | {rules} | {model} | {rules_mark} | {model_mark} |".format(
                id=case["id"],
                vendor=vendor,
                count="yes" if case["should_count"] else "no",
                expected=_money(target),
                rules=_money(rules_got),
                model=_money(model_got),
                rules_mark=_case_mark(case, rules_got, answer, rules_claim),
                model_mark=_case_mark(case, model_got, answer, model_claim),
            )
        )

    lines.extend(["", "## Lumen wording", ""])
    lines.append(
        "Lumen Sourcing Co. hides $1,005 of IEEPA across three lines. "
        "Rules-only is built to miss all three. The model run is scored on whether it labels them `tariff_ieepa`."
    )
    lines.append("")
    lines.append("| Line | Amount | Rules-only label | Model label | Model labeled by |")
    lines.append("| --- | ---: | --- | --- | --- |")
    rules_lines = _wording(bills, demo_output.labels)
    model_lines = _wording(bills, live_output.labels)
    for description in WORDING:
        rules = rules_lines[description]
        model = model_lines[description]
        lines.append(
            f"| {description} | {_money(rules['amount'])} | {rules['category']} | {model['category']} | {model['labeled_by']} |"
        )
    rules_caught = sum(1 for row in rules_lines.values() if row["caught"])
    model_caught = sum(1 for row in model_lines.values() if row["caught"])
    lines.extend(
        [
            "",
            f"Rules-only caught {rules_caught} of 3. Model caught {model_caught} of 3.",
            "",
        ]
    )
    path = data_dir / "eval_results.md"
    path.write_text("\n".join(lines))
    return path


def _write_live_results(data_dir, output) -> None:
    dest = data_dir / "live_results"
    dest.mkdir(exist_ok=True)
    _write_json(dest / "classifications.json", output.labels)
    _write_json(dest / "contract_reviews.json", output.contracts)
    _write_json(dest / "claims.json", output.claims)
    _write_json(dest / "letters.json", output.letters)
    _write_json(dest / "prices.json", output.prices)
    _write_json(dest / "importer_cases.json", output.importer_cases)
    _write_json(dest / "usage.json", output.usage)


def _write_json(path, value) -> None:
    payload = _dump(value)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _dump(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _dump(item) for key, item in value.items()}
    return value


def _gross(claims, name: str) -> Decimal:
    claim = claims.get(name)
    return claim.gross_refundable if claim else Decimal("0")


def _case_mark(case, got, answer, claim) -> str:
    false_positive = got if not case["should_count"] else Decimal("0")
    missed = answer - got if case["should_count"] and got + EXACT < answer else Decimal("0")
    expect_review = bool(case.get("needs_review"))
    got_review = bool(claim and claim.needs_review)
    mark = _mark(case, got, answer, false_positive, missed, expect_review, got_review)
    return "caught" if mark in {"ok", "needs review"} else mark


def _wording(bills, labels) -> dict:
    by_key = {(label.invoice_number, label.line_index): label for label in labels}
    found = {}
    for bill in bills:
        if bill.vendor.name != "Lumen Sourcing Co.":
            continue
        for line in bill.line_items:
            if line.description not in WORDING:
                continue
            label = by_key.get((bill.invoice_number, line.line_index))
            found[line.description] = {
                "amount": line.amount,
                "category": label.category.value if label else "unlabeled",
                "labeled_by": label.labeled_by if label else "",
                "caught": bool(label and label.category.value == "tariff_ieepa"),
            }
    for description in WORDING:
        found.setdefault(
            description,
            {"amount": Decimal("0"), "category": "missing", "labeled_by": "", "caught": False},
        )
    return found


def _money(value: Decimal) -> str:
    return f"${money(value):,.2f}"


def _line_scores(data_dir, bills, labels) -> dict:
    known = {(bill.invoice_number, line.line_index) for bill in bills for line in bill.line_items}
    predicted = {
        (label.invoice_number, label.line_index)
        for label in labels
        if label.category.value == "tariff_ieepa"
    }
    truth = set()
    described = {}
    with (data_dir / "labels.csv").open() as handle:
        for row in csv.DictReader(handle):
            key = (row["invoice_number"], int(row["line_index"]))
            if key not in known or row["category"] != "tariff_ieepa":
                continue
            truth.add(key)
            described[key] = row["description"]
    hit = predicted & truth
    missed = [f"{inv} line {idx}  {described.get((inv, idx), '')}" for inv, idx in sorted(truth - predicted)]
    extra = [f"{inv} line {idx}" for inv, idx in sorted(predicted - truth)]
    return {
        "precision": _ratio(len(hit), len(predicted)),
        "recall": _ratio(len(hit), len(truth)),
        "hit": len(hit),
        "truth": len(truth),
        "flagged": len(predicted),
        "missed": missed,
        "extra": extra,
    }


def _price_scores(truth, prices) -> dict:
    answer = {(item["vendor"], item["sku"]) for item in truth["price_items"]}
    flagged = {(sku.vendor_name, sku.sku) for sku in prices.skus if sku.flagged_amount > 0}
    hit = answer & flagged
    return {
        "precision": _ratio(len(hit), len(flagged)),
        "recall": _ratio(len(hit), len(answer)),
        "hit": len(hit),
        "truth": len(answer),
        "flagged": len(flagged),
        "missed": sorted(answer - flagged),
        "extra": sorted(flagged - answer),
    }


def _ratio(hit: int, total: int) -> float | None:
    if total == 0:
        return None
    return hit / total


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1%}"


def _dollars(value: object) -> Decimal:
    return money(Decimal(str(round(float(value), 2))))


if __name__ == "__main__":
    main()
