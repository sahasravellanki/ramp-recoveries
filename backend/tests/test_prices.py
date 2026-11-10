"""Timing windows, control fallback, and the import-share gate. No PDFs."""

from datetime import date
from decimal import Decimal

from pipeline.prices import Observation, qualify
from pipeline.tariffs import match_increase, rate_increases


def test_rate_increases_skip_cuts_and_match_any_later_hike():
    china = {inc.effective for inc in rate_increases("CN")}
    assert date(2025, 2, 4) in china
    assert date(2025, 3, 4) in china
    assert date(2025, 4, 9) in china
    assert date(2025, 4, 10) in china
    assert date(2025, 5, 14) not in china

    assert match_increase("CN", date(2025, 3, 20)).effective == date(2025, 3, 4)
    april = match_increase("CN", date(2025, 4, 12))
    assert april is not None and april.effective == date(2025, 4, 10)

    assert match_increase("IT", date(2025, 3, 4)) is None
    assert match_increase("IT", date(2025, 5, 15)).effective == date(2025, 4, 5)
    august = match_increase("IT", date(2025, 8, 20))
    assert august is not None and august.effective == date(2025, 8, 7)
    assert any("European Union" in action.name for action in august.actions)

    vietnam = match_increase("VN", date(2025, 9, 1))
    assert vietnam is not None and vietnam.effective == date(2025, 8, 7)
    assert "Vietnam" in vietnam.actions[0].name


def test_category_control_can_reject_and_missing_control_needs_review():
    peer = qualify(
        [
            _obs("Clearpour Glass", "CPG-CAR", date(2024, 10, 1), "80.00", "IT", "glass_carafes"),
            _obs("Clearpour Glass", "CPG-CAR", date(2025, 1, 10), "80.00", "IT", "glass_carafes"),
            _obs("Clearpour Glass", "CPG-CAR", date(2025, 5, 20), "84.40", "IT", "glass_carafes"),
            _obs("Homestead Kiln", "HMK-CAR", date(2024, 9, 1), "40.00", "US", "glass_carafes"),
            _obs("Homestead Kiln", "HMK-CAR", date(2025, 5, 20), "41.60", "US", "glass_carafes"),
        ]
    )
    carafe = next(sku for sku in peer.skus if sku.vendor_name == "Clearpour Glass")
    assert carafe.qualified is False
    assert carafe.needs_review is False
    control = next(test for test in carafe.tests if test.id == "control")
    assert control.status == "fail"
    assert "other suppliers" in control.detail
    assert "more than 2 points" in control.detail
    timing = next(test for test in carafe.tests if test.id == "timing")
    assert timing.status == "pass"
    assert "2025-04-05" in (timing.matched_action or "")

    alone = qualify(
        [
            _obs("Orchard Copper", "ORC-PAN", date(2024, 11, 1), "100.00", "VN", "copper_cookware"),
            _obs("Orchard Copper", "ORC-PAN", date(2025, 4, 1), "100.00", "VN", "copper_cookware"),
            _obs("Orchard Copper", "ORC-PAN", date(2025, 9, 10), "106.00", "VN", "copper_cookware"),
        ]
    )
    pan = alone.skus[0]
    assert pan.qualified is False
    assert pan.needs_review is True
    assert next(test for test in pan.tests if test.id == "control").status == "needs_review"
    matched = next(test for test in pan.tests if test.id == "timing")
    assert matched.status == "pass"
    assert "2025-08-07" in (matched.matched_action or "")
    assert alone.findings == []


def test_jump_above_the_cap_is_claimed_up_to_the_cap_until_twice():
    capped = qualify(_series("105.00", Decimal("0.40")))
    item = next(sku for sku in capped.skus if sku.sku == "IT-PART")
    size = next(test for test in item.tests if test.id == "size")
    assert size.status == "pass"
    assert "Capped at the estimated tariff on import cost" in size.detail
    assert item.qualified is True
    assert item.claim_expected == Decimal("16.00")
    assert item.claim_high == Decimal("20.00")
    finding = next(row for row in capped.findings if row.sku == "IT-PART")
    assert finding.capped_per_unit == Decimal("4.00")
    assert finding.excess_per_unit == Decimal("5.00")
    control = next(test for test in item.tests if test.id == "control")
    assert control.status == "pass"
    assert "more than 2 points" in control.detail

    exact = qualify(_series("108.00", Decimal("0.40")))
    exact_item = next(sku for sku in exact.skus if sku.sku == "IT-PART")
    exact_size = next(test for test in exact_item.tests if test.id == "size")
    assert exact_size.status == "pass"
    assert "Capped at the estimated tariff on import cost" in exact_size.detail
    assert exact_item.claim_expected == Decimal("16.00")

    inside = qualify(_series("105.00", Decimal("0.60")))
    inside_item = next(sku for sku in inside.skus if sku.sku == "IT-PART")
    inside_size = next(test for test in inside_item.tests if test.id == "size")
    assert inside_size.status == "pass"
    assert "Capped at the estimated tariff on import cost" not in inside_size.detail
    assert inside_item.claim_expected == Decimal("20.00")

    too_far = qualify(_series("109.00", Decimal("0.40")))
    too_item = next(sku for sku in too_far.skus if sku.sku == "IT-PART")
    too_size = next(test for test in too_item.tests if test.id == "size")
    assert too_size.status == "fail"
    assert "more than twice" in too_size.detail
    assert too_item.qualified is False
    assert too_far.findings == []


def _series(jump_price: str, share: Decimal) -> list[Observation]:
    return [
        _obs("Millwork", "IT-PART", date(2024, 10, 1), "100.00", "IT", "parts", share),
        _obs("Millwork", "IT-PART", date(2025, 1, 10), "100.00", "IT", "parts", share),
        _obs("Millwork", "IT-PART", date(2025, 5, 15), jump_price, "IT", "parts", share),
        _obs("Millwork", "US-TOOL", date(2024, 10, 1), "50.00", "US", "parts", share),
        _obs("Millwork", "US-TOOL", date(2025, 5, 15), "50.00", "US", "parts", share),
    ]


def _obs(vendor, sku, issued, price, country, category, share: Decimal = Decimal("0.6")) -> Observation:
    return Observation(
        vendor=vendor,
        sku=sku,
        invoice_number=f"{sku}-{issued.isoformat()}",
        line_index=0,
        issued=issued,
        description=sku,
        quantity=Decimal("4"),
        unit_price=Decimal(price),
        country=country,
        hts="70",
        origin_inferred=False,
        import_cost_share=share,
        category_id=category,
        labeled_by="test",
    )
