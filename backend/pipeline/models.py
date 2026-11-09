"""Pydantic models shared across the pipeline.

Dollars are Decimal, quantized to cents at the boundary. The model labels lines;
nothing in here computes a claim.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


class LineCategory(str, Enum):
    tariff_ieepa = "tariff_ieepa"
    tariff_other = "tariff_other"
    product = "product"
    freight = "freight"
    tax = "tax"
    other_fee = "other_fee"
    customs_duty_paid_by_buyer = "customs_duty_paid_by_buyer"


# Labels that mean "this line is a duty or a duty pass-through".
TARIFF_CATEGORIES = {
    LineCategory.tariff_ieepa,
    LineCategory.tariff_other,
    LineCategory.customs_duty_paid_by_buyer,
}


class Decision(str, Enum):
    confident = "confident"
    needs_review = "needs_review"


class ClaimStrength(str, Enum):
    high = "High"
    medium = "Medium"
    low = "Low"
    tracked = "Tracked"


class VendorRef(BaseModel):
    id: str
    name: str


class Address(BaseModel):
    model_config = ConfigDict(extra="ignore")
    line1: str | None = None
    line2: str | None = None
    country: str | None = None


class LineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    line_index: int
    sku: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    country_of_origin: str | None = None
    hts_chapter: str | None = None

    @field_validator("unit_price", "amount", mode="before")
    @classmethod
    def _cents(cls, v: object) -> Decimal:
        return money(Decimal(str(v)))


class LineMathResult(BaseModel):
    line_index: int
    ok: bool
    computed: Decimal
    stated: Decimal
    delta: Decimal


class BillMathCheck(BaseModel):
    """qty * unit_price against the line amount, and the lines against the total."""

    lines_ok: bool
    total_ok: bool
    lines_sum: Decimal
    stated_total: Decimal
    total_delta: Decimal
    line_results: list[LineMathResult] = Field(default_factory=list)

    @property
    def failed(self) -> bool:
        return not (self.lines_ok and self.total_ok)


class Bill(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    vendor: VendorRef
    invoice_number: str
    issued_at: date
    due_at: date | None = None
    paid_at: date | None = None
    amount: Decimal
    currency: str = "USD"
    status: str = "PAID"
    line_items: list[LineItem] = Field(default_factory=list)
    document_url: str | None = None
    document_is_scanned_image: bool = False
    page_count: int = 1
    needs_review: bool = False
    review_reason: str | None = None
    source: str = "bill_pay"
    math: BillMathCheck | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _cents(cls, v: object) -> Decimal:
        return money(Decimal(str(v)))


class Vendor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    contact_email: str | None = None
    phone: str | None = None
    address: Address | None = None
    payment_terms: str | None = None
    primary_country_of_origin: str | None = None


class VendorCredit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    vendor: VendorRef
    credit_memo_number: str
    issued_at: date
    amount: Decimal
    currency: str = "USD"
    status: str = "AVAILABLE"
    memo: str | None = None
    reference: str | None = None
    document_url: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _cents(cls, v: object) -> Decimal:
        return money(Decimal(str(v)))


class LineLabel(BaseModel):
    invoice_number: str
    line_index: int
    category: LineCategory
    decision: Decision
    reason: str
    labeled_by: str
    escalated: bool = False

    @field_validator("reason")
    @classmethod
    def _short_reason(cls, v: str) -> str:
        words = v.split()
        if len(words) > 15:
            return " ".join(words[:15])
        return v


class ProductCategory(BaseModel):
    id: str
    name: str
    imported_likely: bool
    ieepa_rate: Decimal
    examples: str


class SkuTag(BaseModel):
    vendor_name: str
    sku: str
    description: str
    category_id: str | None
    category_name: str | None
    imported_likely: bool
    ieepa_rate: Decimal
    decision: Decision
    reason: str
    labeled_by: str
    country_of_origin: str | None = None
    hts_chapter: str | None = None
    origin_inferred: bool = False
    hts_inferred: bool = False
    import_cost_share: Decimal = Decimal("0.60")


class PriceTest(BaseModel):
    """One check for a price-only or contract-plus-price claim.

    status is pass, fail, or needs_review. needs_review is neither a pass nor a
    fail: the test could not be run, and the item is not claimed.
    """

    id: str
    name: str
    passed: bool
    required: bool
    detail: str
    status: Literal["pass", "fail", "needs_review"] = "fail"
    matched_action: str | None = None


class PriceFinding(BaseModel):
    """One product line whose price passed every required test. amount is the expected claim."""

    vendor_name: str
    sku: str
    invoice_number: str
    line_index: int
    issued_at: date
    description: str
    quantity: Decimal
    unit_price: Decimal
    baseline: Decimal
    expected: Decimal
    excess_per_unit: Decimal
    capped_per_unit: Decimal
    amount: Decimal
    category_id: str
    tariff_rate: Decimal
    labeled_by: str
    low_amount: Decimal = Decimal("0.00")
    high_amount: Decimal = Decimal("0.00")
    origin_inferred: bool = False
    country: str | None = None
    hts_chapter: str | None = None


class SkuPriceSummary(BaseModel):
    vendor_name: str
    sku: str
    baseline: Decimal | None
    observations: int
    benchmark_price: Decimal | None
    benchmark_source: Literal["ramp_network_benchmark"] = "ramp_network_benchmark"
    benchmark_is_mock: Literal[True] = True
    fell_back_after_window: bool | None = None
    flagged_amount: Decimal = Decimal("0.00")
    tests: list[PriceTest] = Field(default_factory=list)
    country: str | None = None
    hts_chapter: str | None = None
    origin_inferred: bool = False
    tariff_rate: Decimal | None = None
    qualified: bool = False
    needs_review: bool = False
    claim_low: Decimal = Decimal("0.00")
    claim_expected: Decimal = Decimal("0.00")
    claim_high: Decimal = Decimal("0.00")
    import_cost_share: Decimal = Decimal("0.60")
    max_unit_jump: Decimal = Decimal("0.00")
    control_percent: Decimal | None = None
    jump_on: date | None = None
    matched_action: str | None = None
    labeled_by: str = ""


class PriceAnalysis(BaseModel):
    findings: list[PriceFinding]
    skus: list[SkuPriceSummary]


class ImporterCase(BaseModel):
    invoice_number: str
    line_index: int
    vendor_name: str
    issued_at: date
    description: str
    amount: Decimal
    guidance: str
    labeled_by: str


class ContractFinding(BaseModel):
    vendor_id: str
    vendor_name: str
    document_url: str | None = None
    mentions_tariffs: bool
    refund_or_credit_clause: bool
    clause_number: str | None = None
    clause_text: str | None = None
    summary: str | None = None
    labeled_by: str


class Evidence(BaseModel):
    invoice_number: str
    line_index: int
    date: date
    description: str
    amount: Decimal
    type: Literal["tariff_ieepa_surcharge", "price_excess", "tariff_other", "vendor_credit"]
    labeled_by: str


class VendorClaim(BaseModel):
    vendor_id: str
    vendor_name: str
    contact_email: str | None = None
    address_lines: list[str] = Field(default_factory=list)
    strength: ClaimStrength | None
    refundable_total: Decimal
    gross_refundable: Decimal
    ieepa_surcharge_total: Decimal
    price_excess_total: Decimal
    credits_applied: Decimal
    non_refundable_total: Decimal
    explicit_surcharge: bool
    price_jump_reverted: bool | None
    contract_mentions_tariffs: bool
    contract_refund_clause: bool
    clause_number: str | None = None
    clause_text: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    evidence_tier: str | None = None
    tier_reasons: list[str] = Field(default_factory=list)
    claim_low: Decimal | None = None
    claim_expected: Decimal | None = None
    claim_high: Decimal | None = None
    origin_inferred_only: bool = False
    needs_review: bool = False

    @property
    def invoice_numbers(self) -> list[str]:
        seen: list[str] = []
        for item in self.evidence:
            if item.amount > 0 and item.type != "tariff_other" and item.invoice_number not in seen:
                seen.append(item.invoice_number)
        return seen


class LetterFacts(BaseModel):
    """The only facts a letter may use. No raw invoices, no unlabeled dollars."""

    vendor_name: str
    vendor_address: list[str]
    buyer_name: str
    window_start: date
    window_end: date
    refundable_total: Decimal
    credits_already_received: Decimal
    credit_memos: list[str]
    invoice_numbers: list[str]
    contract_clause_number: str | None
    contract_clause_text: str | None
    signoff: str


class Letter(BaseModel):
    vendor_name: str
    status: Literal["draft"] = "draft"
    requires_approval: Literal[True] = True
    body: str
    word_count: int
    model: str
    flagged_language: list[str] = Field(default_factory=list)


class Usage(BaseModel):
    calls: dict[str, int] = Field(default_factory=dict)
    input_tokens: dict[str, int] = Field(default_factory=dict)
    output_tokens: dict[str, int] = Field(default_factory=dict)
    cache_read_tokens: dict[str, int] = Field(default_factory=dict)
    cache_write_tokens: dict[str, int] = Field(default_factory=dict)

    def add(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
        self.calls[model] = self.calls.get(model, 0) + 1
        self.input_tokens[model] = self.input_tokens.get(model, 0) + input_tokens
        self.output_tokens[model] = self.output_tokens.get(model, 0) + output_tokens
        self.cache_read_tokens[model] = self.cache_read_tokens.get(model, 0) + cache_read_tokens
        self.cache_write_tokens[model] = self.cache_write_tokens.get(model, 0) + cache_write_tokens
