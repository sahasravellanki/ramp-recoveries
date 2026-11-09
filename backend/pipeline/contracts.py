"""Read supplier contracts and pull out a tariff refund clause, if one exists.

PDFs are matched to vendors by name, not by the link stored in the fixture.
Tier 2 quotes the clause; demo mode uses keyword rules on the same text.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pdfplumber
from pydantic import BaseModel

from .config import Settings
from .llm import call_tool
from .models import ContractFinding, Usage, Vendor

logging.getLogger("pdfminer").setLevel(logging.ERROR)

DEMO_MODEL = "demo-rules:tier2"
_TARIFF = re.compile(r"\b(tariffs?|dut(?:y|ies)|surcharges?|ieepa)\b", re.IGNORECASE)
_REFUND = re.compile(r"\b(refund\w*|credit\w*|pass[- ]through|pro rata)\b", re.IGNORECASE)
_SECTION = re.compile(r"(?m)^(\d+)\.\s+(.+)$")


class _Clause(BaseModel):
    mentions_tariffs: bool
    refund_or_credit_clause: bool
    clause_number: str | None = None
    clause_text: str | None = None
    summary: str | None = None


_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "mentions_tariffs": {"type": "boolean"},
        "refund_or_credit_clause": {"type": "boolean"},
        "clause_number": {"type": ["string", "null"]},
        "clause_text": {
            "type": ["string", "null"],
            "description": "Exact quote from the contract. Null when there is no refund clause.",
        },
        "summary": {"type": ["string", "null"], "description": "One sentence."},
    },
    "required": ["mentions_tariffs", "refund_or_credit_clause", "clause_number", "clause_text", "summary"],
}


def analyze(vendors: list[Vendor], data_dir: Path, settings: Settings, usage: Usage) -> dict[str, ContractFinding]:
    documents = _read_contracts(data_dir / "contracts")
    findings: dict[str, ContractFinding] = {}
    for vendor in vendors:
        match = _match_vendor(vendor.name, documents)
        if match is None:
            continue
        filename, text = match
        if settings.use_demo:
            usage.add(DEMO_MODEL)
            clause = _demo_clause(text)
            labeled_by = DEMO_MODEL
        else:
            clause = _live_clause(vendor.name, text, settings, usage)
            labeled_by = settings.tier2_model
        findings[vendor.name] = ContractFinding(
            vendor_id=vendor.id,
            vendor_name=vendor.name,
            document_url=f"data/contracts/{filename}",
            mentions_tariffs=clause.mentions_tariffs,
            refund_or_credit_clause=clause.refund_or_credit_clause,
            clause_number=clause.clause_number,
            clause_text=clause.clause_text,
            summary=clause.summary,
            labeled_by=labeled_by,
        )
    return findings


def _read_contracts(folder: Path) -> list[tuple[str, str]]:
    documents = []
    if not folder.exists():
        return documents
    for path in sorted(folder.glob("*.pdf")):
        with pdfplumber.open(path) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        documents.append((path.name, text))
    return documents


def _match_vendor(name: str, documents: list[tuple[str, str]]) -> tuple[str, str] | None:
    needle = _normalize(name)
    hits = [(filename, text) for filename, text in documents if needle and needle in _normalize(text)]
    if not hits:
        return None
    # The longest contract that names this vendor. A short name can't steal a longer one's file
    # because the full legal name is what we search for.
    return max(hits, key=lambda item: len(item[1]))


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _sections(text: str) -> list[tuple[str, str, str]]:
    """(number, title, body) for each numbered section."""
    matches = list(_SECTION.finditer(text))
    sections = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = " ".join(text[start:end].split())
        sections.append((match.group(1), match.group(2).strip(), body))
    return sections


def _demo_clause(text: str) -> _Clause:
    mentions = bool(_TARIFF.search(text))
    for number, title, body in _sections(text):
        if not (_TARIFF.search(title) or _TARIFF.search(body)):
            continue
        if not _REFUND.search(body):
            continue
        if re.search(r"pro rata|pass[- ]through", body, re.IGNORECASE):
            summary = f"Section {number} requires the supplier to pass a pro rata share of any refunded duty through to the buyer."
        else:
            summary = f"Section {number} requires the supplier to credit the buyer if the underlying duty is refunded."
        return _Clause(
            mentions_tariffs=True,
            refund_or_credit_clause=True,
            clause_number=number,
            clause_text=body,
            summary=summary,
        )
    return _Clause(
        mentions_tariffs=mentions,
        refund_or_credit_clause=False,
        summary="The contract mentions tariffs but has no refund or credit clause." if mentions else None,
    )


def _live_clause(vendor_name: str, text: str, settings: Settings, usage: Usage) -> _Clause:
    result = call_tool(
        settings,
        settings.tier2_model,
        "You extract contract terms. Quote clause_text exactly from the document, with no paraphrase. "
        "refund_or_credit_clause is true only when the supplier must return money to the buyer if a duty is refunded. "
        "summary is one sentence. Leave clause fields null when there is no such clause.",
        f"Vendor: {vendor_name}\n\nContract text:\n{text}",
        "extract_tariff_clause",
        "Report whether the contract mentions tariffs and quote any refund clause.",
        _SCHEMA,
        _Clause,
        usage,
        max_tokens=1500,
    )
    assert isinstance(result, _Clause)
    return result
