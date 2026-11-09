"""Score the pipeline against the answer key.

Demo mode is what runs without an API key. Keyword rules miss the three
wording traps on purpose. A live run, when a key is set, is scored the same
way against the full answer.

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


def main() -> None:
    settings = get_settings()
    demo = settings.model_copy(update={"demo_mode": True})
    _report(demo, "demo")
    if settings.use_demo:
        print()
        print("Real-model eval was not run. ANTHROPIC_API_KEY is not set, so there is nothing to call.")
        return
    print()
    _report(settings, "live")


def _report(settings, mode: str) -> None:
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
        mark = "ok"
        if false_positive > EXACT:
            mark = "FALSE POSITIVE"
        elif missed > EXACT:
            mark = "missed"
        elif case["should_count"] and abs(got - answer) > EXACT:
            mark = "dollar mismatch"
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
