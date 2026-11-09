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


def _obs(vendor, sku, issued, price, country, category) -> Observation:
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
        import_cost_share=Decimal("0.6"),
        category_id=category,
        labeled_by="test",
    )
