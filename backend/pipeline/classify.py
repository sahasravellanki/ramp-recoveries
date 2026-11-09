"""Label every line of a bill, then escalate the ones that look wrong.

Tier 1 labels a whole bill in one call. A line moves to tier 2 when the first
pass is unsure, when the words and the label disagree, or when the bill's
arithmetic failed. If tier 2 is still unsure, the line stays for a person.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .config import Settings
from .llm import call_tool
from .models import Bill, Decision, LineCategory, LineItem, LineLabel, Usage

# Word-boundary on purpose: "important" is not "import", "duty" is not inside another word.
TARIFF_WORDS = re.compile(
    r"\b(tariffs?|dut(?:y|ies)|imports?|imported|ieepa|customs|section\s*-?\s*(?:301|232|122))\b",
    re.IGNORECASE,
)
DEMO_TIER1 = "demo-rules:tier1"
DEMO_TIER2 = "demo-rules:tier2"

_LABEL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "line_index": {"type": "integer"},
                    "category": {"type": "string", "enum": [c.value for c in LineCategory]},
                    "decision": {"type": "string", "enum": [d.value for d in Decision]},
                    "reason": {"type": "string", "description": "Under 15 words."},
                },
                "required": ["line_index", "category", "decision", "reason"],
            },
        }
    },
    "required": ["lines"],
}

_SYSTEM = """You label invoice lines for a tariff-refund review. You do not do arithmetic.

Categories:
- tariff_ieepa: a surcharge or adjustment that passes an IEEPA tariff on to the buyer. That includes "tariff surcharge", "IEEPA adjustment", and "import cost recovery". It also includes wording that never says tariff when the line is still a duty pass-through, such as "landed cost adjustment", "supplier cost pass-through", and "global sourcing fee".
- tariff_other: a surcharge under a tariff that was NOT struck down, such as Section 301, Section 232 steel or aluminum, or Section 122. These are not refundable.
- customs_duty_paid_by_buyer: the buyer was the importer of record. The line bills them for duty the forwarder paid at entry. This is not a supplier surcharge.
- freight: shipping, freight, handling.
- tax: sales tax.
- other_fee: a fee that is not a tariff, including fuel surcharges and customs brokerage.
- product: the goods themselves.

decision is "confident" or "needs_review". No scores. reason is under 15 words.
Use needs_review when the wording could go either way."""


class _LabeledLine(BaseModel):
    line_index: int
    category: LineCategory
    decision: Decision
    reason: str


class _LabelBatch(BaseModel):
    lines: list[_LabeledLine] = Field(default_factory=list)


def classify_bills(bills: list[Bill], settings: Settings, usage: Usage) -> list[LineLabel]:
    labels: list[LineLabel] = []
    for bill in bills:
        labels.extend(classify_bill(bill, settings, usage))
    return labels


def classify_bill(bill: Bill, settings: Settings, usage: Usage) -> list[LineLabel]:
    if not bill.line_items:
        return []
    math_failed = bool(bill.math and bill.math.failed)
    first = _label_batch(bill.line_items, bill, settings, usage, tier=1)
    escalate = [
        line
        for line in bill.line_items
        if _should_escalate(line, first[line.line_index], math_failed)
    ]
    final = dict(first)
    if escalate:
        second = _label_batch(escalate, bill, settings, usage, tier=2)
        for line in escalate:
            label = second.get(line.line_index, first[line.line_index])
            final[line.line_index] = label.model_copy(update={"escalated": True})
    return [final[line.line_index] for line in bill.line_items]


def _should_escalate(line: LineItem, label: LineLabel, math_failed: bool) -> bool:
    if label.decision is Decision.needs_review or math_failed:
        return True
    words_say_tariff = bool(TARIFF_WORDS.search(line.description))
    label_is_tariff = label.category in {
        LineCategory.tariff_ieepa,
        LineCategory.tariff_other,
        LineCategory.customs_duty_paid_by_buyer,
    }
    return words_say_tariff != label_is_tariff


def _label_batch(
    lines: list[LineItem], bill: Bill, settings: Settings, usage: Usage, tier: int
) -> dict[int, LineLabel]:
    model = DEMO_TIER1 if tier == 1 else DEMO_TIER2
    if settings.use_demo:
        usage.add(model)
        return {line.line_index: _demo_label(line, bill.invoice_number, tier) for line in lines}
    live_model = settings.tier1_model if tier == 1 else settings.tier2_model
    payload = {
        "vendor": bill.vendor.name,
        "invoice_number": bill.invoice_number,
        "lines": [
            {"line_index": line.line_index, "sku": line.sku, "description": line.description}
            for line in lines
        ],
    }
    import json

    batch = call_tool(
        settings,
        live_model,
        _SYSTEM,
        json.dumps(payload),
        "label_invoice_lines",
        "Label each line. Return one entry per line_index you were given.",
        _LABEL_SCHEMA,
        _LabelBatch,
        usage,
    )
    assert isinstance(batch, _LabelBatch)
    found = {item.line_index: item for item in batch.lines}
    out: dict[int, LineLabel] = {}
    for line in lines:
        item = found.get(line.line_index)
        if item is None:
            out[line.line_index] = LineLabel(
                invoice_number=bill.invoice_number,
                line_index=line.line_index,
                category=LineCategory.product,
                decision=Decision.needs_review,
                reason="Model returned no label for this line",
                labeled_by=live_model,
            )
            continue
        out[line.line_index] = LineLabel(
            invoice_number=bill.invoice_number,
            line_index=line.line_index,
            category=item.category,
            decision=item.decision,
            reason=item.reason,
            labeled_by=live_model,
        )
    return out


def _demo_label(line: LineItem, invoice_number: str, tier: int) -> LineLabel:
    text = line.description.lower()
    category, reason = _demo_category(text)
    decision = Decision.confident
    # Tier 2 is the stricter pass: tariff-ish words with no specific rule stay open.
    if tier == 2 and category is LineCategory.product and TARIFF_WORDS.search(line.description):
        decision = Decision.needs_review
        reason = "Tariff keywords but no clear surcharge"
    return LineLabel(
        invoice_number=invoice_number,
        line_index=line.line_index,
        category=category,
        decision=decision,
        reason=reason,
        labeled_by=DEMO_TIER1 if tier == 1 else DEMO_TIER2,
    )


def _demo_category(text: str) -> tuple[LineCategory, str]:
    if "sales tax" in text:
        return LineCategory.tax, "Sales tax line"
    if re.search(r"section\s*-?\s*(301|232|122)", text):
        return LineCategory.tariff_other, "Section 301, 232, or 122 duty, not IEEPA"
    if "brokerage" in text:
        return LineCategory.other_fee, "Brokerage fee, not a duty"
    if "customs duty" in text or "duty paid" in text or "importer of record" in text:
        return LineCategory.customs_duty_paid_by_buyer, "Customs duty billed to the buyer"
    if "ieepa" in text:
        return LineCategory.tariff_ieepa, "Named IEEPA adjustment"
    if "tariff" in text:
        return LineCategory.tariff_ieepa, "Tariff surcharge line"
    if "import cost" in text:
        return LineCategory.tariff_ieepa, "Import cost recovery surcharge"
    if "fuel surcharge" in text or text.strip() == "fuel":
        return LineCategory.other_fee, "Fuel surcharge, not a tariff"
    if any(word in text for word in ("freight", "shipping", "handling")):
        return LineCategory.freight, "Freight or shipping charge"
    return LineCategory.product, "Product line, no tariff language"
