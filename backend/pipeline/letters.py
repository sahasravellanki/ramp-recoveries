"""Draft a claim letter from a verified facts object and nothing else.

The model never sees invoices, contracts, or the ledger. It sees the facts JSON.
Demo mode fills a template from the same object. Nothing here is sent: every
letter stays a draft until a person approves it.
"""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel

from .config import BUYER_NAME, SIGN_OFF, WINDOW_END, WINDOW_START, Settings
from .llm import call_tool
from .models import Letter, LetterFacts, Usage, VendorClaim, money

_THREATS = re.compile(
    r"\b(lawsuit|sue\b|attorney|counsel|liable|liability|breach|penalty|penalties|demand|compel)\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'./$%-]*")
WORD_LIMIT = 250

_SYSTEM = f"""Write a short business letter from the facts JSON and nothing else.

Rules:
- Use only numbers, dates, invoice numbers, and clause text that appear in the JSON. Do not invent any.
- Put the vendor address and the date at the top. Put the request at the end.
- Cite the invoice numbers. Do not ask whether the supplier was the importer of record.
- Quote contract_clause_text only when it is present, and quote it exactly.
- Mention credits_already_received when it is above zero, including the memo numbers.
- The request is soft, in this spirit: "If you've received a refund for these duties, we'd appreciate a credit for our share." Ask for a vendor credit of exactly refundable_total. No legal threats, no demands, no mention of lawyers or liability.
- Under {WORD_LIMIT} words.
- End with exactly this line: {SIGN_OFF}"""


class _Draft(BaseModel):
    body: str


_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"body": {"type": "string"}},
    "required": ["body"],
}


def draft_all(claims: list[VendorClaim], settings: Settings, usage: Usage, today: date | None = None) -> list[Letter]:
    letters = []
    for claim in claims:
        if claim.refundable_total <= 0:
            continue
        facts = _facts(claim)
        if settings.use_demo:
            usage.add("demo-rules:tier2")
            body = _template(facts, today or date.today())
            model = "demo-rules:tier2"
        else:
            body = _live(facts, settings, usage)
            model = settings.tier2_model
        letters.append(
            Letter(
                vendor_name=claim.vendor_name,
                body=body,
                word_count=len(_WORD.findall(body)),
                model=model,
                flagged_language=_THREATS.findall(body),
            )
        )
    for letter in letters:
        if letter.word_count > WORD_LIMIT:
            raise RuntimeError(f"Letter to {letter.vendor_name} is {letter.word_count} words, over {WORD_LIMIT}.")
    return letters


def _facts(claim: VendorClaim) -> LetterFacts:
    credits = [item for item in claim.evidence if item.type == "vendor_credit"]
    return LetterFacts(
        vendor_name=claim.vendor_name,
        vendor_address=claim.address_lines,
        buyer_name=BUYER_NAME,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        refundable_total=claim.refundable_total,
        credits_already_received=claim.credits_applied,
        credit_memos=[f"{item.invoice_number} on {item.date.isoformat()} for ${money(-item.amount):,.2f}" for item in credits],
        invoice_numbers=claim.invoice_numbers,
        contract_clause_number=claim.clause_number if claim.contract_refund_clause else None,
        contract_clause_text=claim.clause_text if claim.contract_refund_clause else None,
        signoff=SIGN_OFF,
    )


def _template(facts: LetterFacts, today: date) -> str:
    address = "\n".join(facts.vendor_address)
    invoices = _invoice_list(facts.invoice_numbers)
    paragraphs = [
        facts.vendor_name,
        address,
        "",
        today.strftime("%B %-d, %Y"),
        "",
        f"Re: IEEPA tariff costs billed to {facts.buyer_name}",
        "",
        "Hello,",
        "",
        (
            f"The IEEPA tariffs were struck down in February 2026, and importers are now being refunded. "
            f"Between {facts.window_start:%B %-d, %Y} and {facts.window_end:%B %-d, %Y}, some of those costs "
            f"showed up on your invoices to us."
        ),
        "",
        f"The invoices are {invoices}.",
    ]
    if facts.credits_already_received > 0:
        memos = "; ".join(facts.credit_memos)
        paragraphs += ["", f"You have already credited us ${facts.credits_already_received:,.2f} ({memos}), and that is subtracted below."]
    if facts.contract_clause_text and facts.contract_clause_number:
        paragraphs += ["", f'Section {facts.contract_clause_number} of our agreement says: "{_quote(facts.contract_clause_text)}"']
    paragraphs += [
        "",
        (
            f"If you've received a refund for these duties, we'd appreciate a credit for our share, "
            f"${facts.refundable_total:,.2f}, applied to our next bill."
        ),
        "",
        "Thank you,",
        facts.signoff,
    ]
    return "\n".join(paragraphs)


def _quote(clause_text: str) -> str:
    """The full clause when it fits; otherwise the one sentence that creates the obligation, still verbatim."""
    if len(_WORD.findall(clause_text)) <= 70:
        return clause_text
    sentences = re.split(r"(?<=\.)\s+", clause_text)
    for sentence in sentences:
        if re.search(r"refund|credit|pass[- ]through|pro rata", sentence, re.IGNORECASE):
            return sentence.strip()
    return clause_text


def _invoice_list(numbers: list[str]) -> str:
    if len(numbers) <= 14:
        return ", ".join(numbers)
    head = ", ".join(numbers[:8])
    return f"{head}, and {len(numbers) - 8} more through {numbers[-1]}"


def _live(facts: LetterFacts, settings: Settings, usage: Usage) -> str:
    draft = call_tool(
        settings,
        settings.tier2_model,
        _SYSTEM,
        facts.model_dump_json(),
        "draft_claim_letter",
        "Draft the letter from the facts JSON only.",
        _SCHEMA,
        _Draft,
        usage,
        max_tokens=1200,
    )
    assert isinstance(draft, _Draft)
    return draft.body
