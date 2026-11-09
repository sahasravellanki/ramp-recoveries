"""What each SKU is, and whether an IEEPA tariff could plausibly sit inside its price.

The table is hand-written and the rates are approximate. Tier 1 only picks a
category; the rate comes from the table, never from the model.
"""

from __future__ import annotations

import json
from decimal import Decimal

from pydantic import BaseModel, Field

from .config import Settings
from .llm import call_tool
from .models import Bill, Decision, ProductCategory, SkuTag, Usage

DEMO_MODEL = "demo-rules:tier1"

# Order is longest-prefix-first at match time. Rates are rough IEEPA pass-through
# ceilings, not the statutory schedule.
CATEGORIES: list[ProductCategory] = [
    ProductCategory(id="foodservice_cups", name="Foodservice cups", imported_likely=True, ieepa_rate=Decimal("0.20"), examples="paper hot and cold cups"),
    ProductCategory(id="foodservice_lids", name="Foodservice lids", imported_likely=True, ieepa_rate=Decimal("0.20"), examples="sip, flat, and dome lids"),
    ProductCategory(id="cup_sleeves", name="Cup sleeves", imported_likely=True, ieepa_rate=Decimal("0.20"), examples="corrugated cup sleeves"),
    ProductCategory(id="takeout_packaging", name="Takeout packaging", imported_likely=True, ieepa_rate=Decimal("0.20"), examples="bags, pastry boxes, trays, tissue"),
    ProductCategory(id="napkins", name="Napkins", imported_likely=True, ieepa_rate=Decimal("0.20"), examples="dispenser and beverage napkins"),
    ProductCategory(id="straws_and_stirrers", name="Straws and stirrers", imported_likely=True, ieepa_rate=Decimal("0.15"), examples="paper straws, wood stirrers"),
    ProductCategory(id="labels_and_tape", name="Labels and tape", imported_likely=True, ieepa_rate=Decimal("0.15"), examples="seal labels, packing tape, gift sleeves"),
    ProductCategory(id="espresso_equipment", name="Espresso machine parts", imported_likely=True, ieepa_rate=Decimal("0.20"), examples="group heads, burrs, pumps, gaskets"),
    ProductCategory(id="barista_tools", name="Barista tools", imported_likely=False, ieepa_rate=Decimal("0.00"), examples="tampers and pitchers made domestically"),
    ProductCategory(id="equipment_service", name="Equipment service", imported_likely=False, ieepa_rate=Decimal("0.00"), examples="on-site labor, billed by the hour"),
    ProductCategory(id="pos_electronics", name="POS electronics", imported_likely=True, ieepa_rate=Decimal("0.25"), examples="displays, printers, scanners, drawers, cables"),
    ProductCategory(id="staff_apparel", name="Staff apparel", imported_likely=True, ieepa_rate=Decimal("0.25"), examples="aprons, tees, caps"),
    ProductCategory(id="cafe_linens", name="Cafe linens", imported_likely=True, ieepa_rate=Decimal("0.20"), examples="bar towels, table runners"),
    ProductCategory(id="office_supplies", name="Office supplies", imported_likely=False, ieepa_rate=Decimal("0.00"), examples="paper, toner, pens, gloves, cleaner"),
    ProductCategory(id="freight_and_fees", name="Freight and fees", imported_likely=False, ieepa_rate=Decimal("0.00"), examples="shipping, surcharges, tax, duty lines"),
]

_BY_ID = {c.id: c for c in CATEGORIES}

# Longest prefix wins.
_SKU_PREFIXES: list[tuple[str, str]] = sorted(
    [
        ("NWP-HCUP", "foodservice_cups"),
        ("NWP-CCUP", "foodservice_cups"),
        ("NWP-CUP", "foodservice_cups"),
        ("NWP-HLID", "foodservice_lids"),
        ("NWP-CLID", "foodservice_lids"),
        ("NWP-LID", "foodservice_lids"),
        ("NWP-HSLV", "cup_sleeves"),
        ("NWP-SLV", "cup_sleeves"),
        ("NWP-BAG", "takeout_packaging"),
        ("NWP-BOX", "takeout_packaging"),
        ("NWP-TRAY", "takeout_packaging"),
        ("NWP-TIS", "takeout_packaging"),
        ("NWP-NAP", "napkins"),
        ("NWP-STRAW", "straws_and_stirrers"),
        ("NWP-STIR", "straws_and_stirrers"),
        ("NWP-TAPE", "labels_and_tape"),
        ("NWP-LABEL", "labels_and_tape"),
        ("NWP-GIFT", "labels_and_tape"),
        ("HP-GRP", "espresso_equipment"),
        ("HP-PUMP", "espresso_equipment"),
        ("HP-BURR", "espresso_equipment"),
        ("HP-HEAT", "espresso_equipment"),
        ("HP-PF", "espresso_equipment"),
        ("HP-FLOW", "espresso_equipment"),
        ("HP-SHWR", "espresso_equipment"),
        ("HP-GSK", "espresso_equipment"),
        ("HP-TAMP", "barista_tools"),
        ("HP-PITCH", "barista_tools"),
        ("HP-SVC", "equipment_service"),
        ("ALT-", "pos_electronics"),
        ("KST-APR", "staff_apparel"),
        ("KST-TEE", "staff_apparel"),
        ("KST-CAP", "staff_apparel"),
        ("KST-TWL", "cafe_linens"),
        ("KST-TBL", "cafe_linens"),
        ("BOS-", "office_supplies"),
    ],
    key=lambda pair: len(pair[0]),
    reverse=True,
)

_DESCRIPTION_RULES: list[tuple[str, str]] = [
    ("gift card", "labels_and_tape"),
    ("label", "labels_and_tape"),
    ("tape", "labels_and_tape"),
    ("sleeve", "cup_sleeves"),
    ("lid", "foodservice_lids"),
    ("cup", "foodservice_cups"),
    ("straw", "straws_and_stirrers"),
    ("stir", "straws_and_stirrers"),
    ("napkin", "napkins"),
    ("bag", "takeout_packaging"),
    ("box", "takeout_packaging"),
    ("tissue", "takeout_packaging"),
    ("tray", "takeout_packaging"),
    ("portafilter", "espresso_equipment"),
    ("burr", "espresso_equipment"),
    ("group head", "espresso_equipment"),
    ("gasket", "espresso_equipment"),
    ("tamper", "barista_tools"),
    ("pitcher", "barista_tools"),
    ("service", "equipment_service"),
    ("printer", "pos_electronics"),
    ("scanner", "pos_electronics"),
    ("tablet", "pos_electronics"),
    ("cable", "pos_electronics"),
    ("apron", "staff_apparel"),
    ("tee", "staff_apparel"),
    ("towel", "cafe_linens"),
    ("runner", "cafe_linens"),
    ("paper", "office_supplies"),
    ("toner", "office_supplies"),
    ("glove", "office_supplies"),
]


class _SkuAssignment(BaseModel):
    sku: str
    category_id: str | None
    decision: Decision
    reason: str


class _SkuBatch(BaseModel):
    skus: list[_SkuAssignment] = Field(default_factory=list)


_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "skus": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "sku": {"type": "string"},
                    "category_id": {"type": ["string", "null"], "enum": [c.id for c in CATEGORIES] + [None]},
                    "decision": {"type": "string", "enum": ["confident", "needs_review"]},
                    "reason": {"type": "string"},
                },
                "required": ["sku", "category_id", "decision", "reason"],
            },
        }
    },
    "required": ["skus"],
}


def tag_skus(bills: list[Bill], settings: Settings, usage: Usage) -> dict[tuple[str, str], SkuTag]:
    """One tag per vendor + SKU, taken from the product lines only."""
    seen: dict[tuple[str, str], tuple[str, str]] = {}
    for bill in bills:
        for line in bill.line_items:
            seen.setdefault((bill.vendor.name, line.sku), (line.description, bill.vendor.name))
    if settings.use_demo:
        usage.add(DEMO_MODEL)
        return {(vendor, sku): _demo_tag(vendor, sku, description) for (vendor, sku), (description, _vendor) in seen.items()}
    return _live_tag(seen, settings, usage)


def category_for(tag: SkuTag | None) -> ProductCategory | None:
    if tag is None or tag.category_id is None:
        return None
    return _BY_ID.get(tag.category_id)


def _demo_tag(vendor: str, sku: str, description: str) -> SkuTag:
    category_id = _match(sku, description)
    category = _BY_ID.get(category_id) if category_id else None
    if category is None:
        return SkuTag(
            vendor_name=vendor,
            sku=sku,
            description=description,
            category_id=None,
            category_name=None,
            imported_likely=False,
            ieepa_rate=Decimal("0.00"),
            decision=Decision.confident,
            reason="Not a product SKU",
            labeled_by=DEMO_MODEL,
        )
    return SkuTag(
        vendor_name=vendor,
        sku=sku,
        description=description,
        category_id=category.id,
        category_name=category.name,
        imported_likely=category.imported_likely,
        ieepa_rate=category.ieepa_rate,
        decision=Decision.confident,
        reason=f"Matched {category.name}",
        labeled_by=DEMO_MODEL,
    )


def _match(sku: str, description: str) -> str | None:
    for prefix, category_id in _SKU_PREFIXES:
        if sku.startswith(prefix):
            return category_id
    text = description.lower()
    for needle, category_id in _DESCRIPTION_RULES:
        if needle in text:
            return category_id
    return None


def _live_tag(seen: dict[tuple[str, str], tuple[str, str]], settings: Settings, usage: Usage) -> dict[tuple[str, str], SkuTag]:
    payload = {
        "categories": [c.model_dump(mode="json") for c in CATEGORIES],
        "skus": [
            {"vendor": vendor, "sku": sku, "description": description}
            for (vendor, sku), (description, _v) in seen.items()
        ],
    }
    batch = call_tool(
        settings,
        settings.tier1_model,
        "Assign each SKU one category id from the list, or null if it is a fee, tax, or surcharge rather than a product. "
        "Do not invent categories. reason under 15 words.",
        json.dumps(payload),
        "tag_skus",
        "Tag every SKU with a category id.",
        _SCHEMA,
        _SkuBatch,
        usage,
    )
    assert isinstance(batch, _SkuBatch)
    by_sku = {item.sku: item for item in batch.skus}
    out: dict[tuple[str, str], SkuTag] = {}
    for (vendor, sku), (description, _v) in seen.items():
        item = by_sku.get(sku)
        category = _BY_ID.get(item.category_id) if item and item.category_id else None
        out[(vendor, sku)] = SkuTag(
            vendor_name=vendor,
            sku=sku,
            description=description,
            category_id=category.id if category else None,
            category_name=category.name if category else None,
            imported_likely=category.imported_likely if category else False,
            ieepa_rate=category.ieepa_rate if category else Decimal("0.00"),
            decision=item.decision if item else Decision.needs_review,
            reason=item.reason if item else "Model returned no category",
            labeled_by=settings.tier1_model,
        )
    return out

