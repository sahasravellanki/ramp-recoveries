#!/usr/bin/env python3
"""Generate the fictional sample dataset for Ramp Recoveries.

Everything here is invented: the buyer, every supplier, every address, every
price. Six suppliers are each a deliberate test case for the tariff
pass-through detector (see SUPPLIER NOTES below). Output is deterministic for a
fixed seed.

Run from the repo root:

    python scripts/make_sample_data.py

Outputs (all under data/):
    invoices/*.pdf          one PDF per invoice (3 rendered as "scans")
    contracts/*.pdf         supplier contracts shown under Vendors > Contracts
    labels.csv              per-line categories, the eval ground truth
    ground_truth.json       expected claim totals per supplier
    bills.json              invoices shaped like Ramp API bill objects
    vendors.json            suppliers shaped like Ramp vendor objects
    vendor_credits.json     the Northwind credit memo

SUPPLIER NOTES
    Northwind Packaging      explicit "Tariff Surcharge (12%)" line, refundable; contract credits
                             surcharges back if duties are refunded; one $500 credit memo already issued
    Harbor & Pine            no surcharge line; imported unit prices +16% Mar 2025 to Feb 2026; contract
                             has a pro rata pass-through clause
    Altamesa Electronics     20% surcharge labeled "Import Cost Recovery" then renamed "IEEPA Adj."; no contract
    Kestrel Textiles         "Section 301 adjustment" (not IEEPA, not refundable); generic contract
    Brightline Office        domestic control, ~2%/yr drift, "Fuel surcharge" decoy line
    Pacific Freight          Sunbird was importer of record; bills "Customs duty paid on entry"
"""

from __future__ import annotations

import csv
import io
import json
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageFilter
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

rl_config.invariant = 1  # deterministic PDF bytes (no timestamps / random IDs)

SEED = 20260220
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
sys.path.insert(0, str(ROOT / "backend"))
INVOICE_DIR = DATA_DIR / "invoices"
CONTRACT_DIR = DATA_DIR / "contracts"

BUYER = {
    "name": "Sunbird Cafe Group",
    "attn": "Accounts Payable",
    "address_line1": "1820 Shattuck Ave",
    "address_line2": "Berkeley, CA 94709",
}
TARIFF_WINDOW_START = date(2025, 2, 4)
TARIFF_WINDOW_END = date(2026, 2, 20)
INVOICE_RANGE = ((2024, 7), (2026, 3))
TAX_RATE = Decimal("0.1025")

CENT = Decimal("0.01")

# Line categories (labels.csv). Keep in sync with the pipeline.
TARIFF_IEEPA = "tariff_ieepa"
TARIFF_OTHER = "tariff_other"
PRODUCT = "product"
FREIGHT = "freight"
TAX = "tax"
OTHER_FEE = "other_fee"
CUSTOMS_DUTY_PAID_BY_BUYER = "customs_duty_paid_by_buyer"


def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def fmt(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def month_range(start: tuple[int, int], end: tuple[int, int], step: int = 1):
    year, month = start
    while (year, month) <= end:
        yield year, month
        month += step
        while month > 12:
            month -= 12
            year += 1


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class CatalogItem:
    sku: str
    description: str
    base_price: Decimal
    imported: bool = False
    country: str | None = None
    hts: str | None = None
    omit_origin: bool = False
    omit_hts: bool = False


@dataclass
class Supplier:
    key: str
    name: str
    prefix: str
    address: list[str]
    email: str
    phone: str
    layout: str  # "classic" | "ledger" | "mono"
    terms_days: int
    catalog: list[CatalogItem] = field(default_factory=list)
    contract_file: str | None = None
    country_of_origin: str = "US"
    id: str = ""


@dataclass
class Line:
    sku: str
    description: str
    qty: Decimal
    unit_price: Decimal
    category: str
    baseline_unit_price: Decimal | None = None  # set when price embeds a tariff
    country: str | None = None
    hts: str | None = None
    keyword_hidden: bool = False  # true IEEPA wording the demo keyword rules are meant to miss

    @property
    def amount(self) -> Decimal:
        return money(self.qty * self.unit_price)

    @property
    def embedded_tariff(self) -> Decimal:
        if self.baseline_unit_price is None:
            return Decimal("0")
        return money((self.unit_price - self.baseline_unit_price) * self.qty)


@dataclass
class Invoice:
    supplier: Supplier
    number: str
    issued: date
    lines: list[Line]
    kind: str = "invoice"  # "invoice" | "credit_memo"
    scanned: bool = False
    memo: str | None = None
    reference: str | None = None
    id: str = ""

    @property
    def due(self) -> date:
        return self.issued + timedelta(days=self.supplier.terms_days)

    @property
    def product_subtotal(self) -> Decimal:
        return sum((l.amount for l in self.lines if l.category == PRODUCT), Decimal("0"))

    @property
    def tax(self) -> Decimal:
        return money(self.product_subtotal * TAX_RATE)

    @property
    def total(self) -> Decimal:
        return sum((l.amount for l in self.lines), Decimal("0")) + self.tax

    @property
    def filename(self) -> str:
        return f"{self.number}.pdf"

    def all_lines(self) -> list[Line]:
        """Table lines plus the sales tax as a trailing line (for labels/bills)."""
        out = list(self.lines)
        if self.tax:
            out.append(
                Line("TAX", f"Sales tax ({TAX_RATE * 100:.2f}%)", Decimal("1"), self.tax, TAX)
            )
        return out


# --------------------------------------------------------------------------- #
# Suppliers
# --------------------------------------------------------------------------- #


def D(s: str) -> Decimal:
    return Decimal(s)


SUPPLIERS: dict[str, Supplier] = {
    "northwind": Supplier(
        key="northwind",
        name="Northwind Packaging Co.",
        prefix="NWP",
        address=["4410 Industrial Pkwy", "Tacoma, WA 98421"],
        email="ar@northwindpackaging.example",
        phone="(253) 555-0142",
        layout="classic",
        terms_days=30,
        country_of_origin="CN",
        contract_file="northwind-packaging-supply-agreement.pdf",
        catalog=[
            CatalogItem("NWP-CUP12", "12 oz double-wall hot cup, kraft (case of 500)", D("61.50"), True),
            CatalogItem("NWP-CUP16", "16 oz double-wall hot cup, kraft (case of 500)", D("68.00"), True),
            CatalogItem("NWP-LID16", "Sip-through lid, black, fits 12/16 oz (case of 1000)", D("42.25"), True),
            CatalogItem("NWP-SLV", "Corrugated cup sleeve, printed (case of 1000)", D("38.90"), True),
            CatalogItem("NWP-BAG4", "Kraft takeout bag #4 (bundle of 500)", D("29.75"), True),
            CatalogItem("NWP-NAP", "Dispenser napkins, 1-ply (case of 6000)", D("44.10"), True),
            CatalogItem("NWP-STRAW", "Paper straws 7.75 in (case of 2400)", D("33.60"), True),
        ],
    ),
    "harborpine": Supplier(
        key="harborpine",
        name="Harbor & Pine Coffee Equipment",
        prefix="HPC",
        address=["212 Pier Street, Suite 4", "Oakland, CA 94607"],
        email="billing@harborandpine.example",
        phone="(510) 555-0188",
        layout="ledger",
        terms_days=45,
        country_of_origin="IT",
        contract_file="harbor-and-pine-equipment-and-service-agreement.pdf",
        catalog=[
            CatalogItem("HP-GRP61", "E61 group head assembly, chrome (Italy)", D("1250.00"), True),
            CatalogItem("HP-PUMP", "Rotary vane pump 100 L/h with motor (Italy)", D("610.00"), True),
            CatalogItem("HP-BURR64", "64 mm flat burr set, titanium-coated (Italy)", D("485.00"), True),
            CatalogItem("HP-HEAT", "Steam boiler heating element 2.8 kW (Italy)", D("395.00"), True),
            CatalogItem("HP-PF58", "58 mm bottomless portafilter, walnut handle (Italy)", D("265.00"), True),
            CatalogItem("HP-FLOW", "Volumetric flow meter kit, 2-group (Italy)", D("210.00"), True),
            CatalogItem("HP-SHWR", "Precision shower screen, 200 micron (Italy)", D("89.00"), True),
            CatalogItem("HP-GSK", "Group head gasket 8.5 mm, pack of 10 (Italy)", D("68.00"), True),
            CatalogItem("HP-TAMP", "Calibrated tamper 58.4 mm (made in USA)", D("95.00"), False),
            CatalogItem("HP-PITCH", "Steaming pitcher 20 oz, stainless (USA)", D("28.00"), False),
            CatalogItem("HP-SVC", "On-site espresso machine service, per hour", D("125.00"), False),
        ],
    ),
    "altamesa": Supplier(
        key="altamesa",
        name="Altamesa Electronics Supply",
        prefix="ALT",
        address=["9000 Mesa Verde Rd, Bldg C", "Chandler, AZ 85226"],
        email="accounts@altamesa-electronics.example",
        phone="(480) 555-0117",
        layout="mono",
        terms_days=30,
        country_of_origin="CN",
        contract_file=None,
        catalog=[
            CatalogItem("ALT-POS10", "10.1 in POS display tablet", D("219.00"), True),
            CatalogItem("ALT-PRN", "Thermal receipt printer, USB/Ethernet", D("164.00"), True),
            CatalogItem("ALT-SCN", "2D barcode scanner, wired", D("88.00"), True),
            CatalogItem("ALT-CBL", "USB-C cable 2 m (pack of 10)", D("31.00"), True),
            CatalogItem("ALT-PSU", "Replacement 24 V power supply", D("27.50"), True),
            CatalogItem("ALT-CASH", "Cash drawer 16 in, 5 bill / 8 coin", D("112.00"), True),
        ],
    ),
    "kestrel": Supplier(
        key="kestrel",
        name="Kestrel Textiles",
        prefix="KST",
        address=["77 Loom Street", "Fall River, MA 02721"],
        email="invoices@kestreltextiles.example",
        phone="(508) 555-0163",
        layout="ledger",
        terms_days=30,
        country_of_origin="CN",
        contract_file="kestrel-textiles-master-supply-agreement.pdf",
        catalog=[
            CatalogItem("KST-APR", "Canvas barista apron, charcoal", D("24.00"), True),
            CatalogItem("KST-TWL", "Bar towel 16 x 19 in (dozen)", D("18.50"), True),
            CatalogItem("KST-TEE", "Staff tee, embroidered logo", D("14.75"), True),
            CatalogItem("KST-CAP", "Dad cap, embroidered logo", D("11.20"), True),
            CatalogItem("KST-TBL", "Linen table runner, natural", D("32.00"), True),
        ],
    ),
    "brightline": Supplier(
        key="brightline",
        name="Brightline Office Supply",
        prefix="BOS",
        address=["1500 Harbor Bay Pkwy", "Alameda, CA 94502"],
        email="ar@brightlineoffice.example",
        phone="(510) 555-0199",
        layout="classic",
        terms_days=30,
        country_of_origin="US",
        contract_file="brightline-office-supply-agreement.pdf",
        catalog=[
            CatalogItem("BOS-PPR", "Copy paper 20 lb, case of 10 reams", D("52.00")),
            CatalogItem("BOS-TNR", "Toner cartridge, black", D("79.00")),
            CatalogItem("BOS-PEN", "Gel pens, black (box of 12)", D("9.60")),
            CatalogItem("BOS-REC", "Receipt roll 3 1/8 in (case of 50)", D("41.00")),
            CatalogItem("BOS-CLN", "Surface cleaner, 1 gal", D("17.40")),
            CatalogItem("BOS-GLV", "Nitrile gloves M (case of 1000)", D("58.00")),
        ],
    ),
    "pacific": Supplier(
        key="pacific",
        name="Pacific Freight Forwarding",
        prefix="PFF",
        address=["601 Maritime Street", "Oakland, CA 94607"],
        email="ar@pacificfreightfwd.example",
        phone="(510) 555-0121",
        layout="mono",
        terms_days=15,
        country_of_origin="US",
        contract_file=None,
    ),
    "lumen": Supplier(
        key="lumen",
        name="Lumen Sourcing Co.",
        prefix="LUM",
        address=["88 Battery Street", "San Francisco, CA 94111"],
        email="ap@lumensourcing.example",
        phone="(415) 555-0174",
        layout="classic",
        terms_days=30,
        country_of_origin="CN",
        catalog=[
            CatalogItem("LUM-CUP", "12 oz hot cup, white (case of 500)", D("40.00"), True, country="CN", hts="48"),
        ],
    ),
    "mill": Supplier(
        key="mill",
        name="Mill & Alloy",
        prefix="MLA",
        address=["410 Foundry Road", "Fontana, CA 92335"],
        email="billing@millandalloy.example",
        phone="(909) 555-0133",
        layout="classic",
        terms_days=30,
        country_of_origin="CN",
        catalog=[
            CatalogItem("MLA-SHT", "Hot-rolled steel sheet, 4 x 8 ft", D("180.00"), True, country="CN", hts="72"),
        ],
    ),
    "early": Supplier(
        key="early",
        name="Early Rise Paper",
        prefix="ERP",
        address=["12 Canal Street", "Stockton, CA 95202"],
        email="ar@earlyrisepaper.example",
        phone="(209) 555-0166",
        layout="classic",
        terms_days=30,
        country_of_origin="CN",
        catalog=[
            CatalogItem("ERP-CUP", "12 oz hot cup, kraft (case of 500)", D("40.00"), True, country="CN", hts="48"),
            CatalogItem("ERP-DOM", "Kraft napkin, made in USA (case of 4000)", D("12.00"), False, country="US", hts="48"),
        ],
    ),
    "homestead": Supplier(
        key="homestead",
        name="Homestead Kiln",
        prefix="HMK",
        address=["640 Clay Avenue", "Fresno, CA 93706"],
        email="accounts@homesteadkiln.example",
        phone="(559) 555-0104",
        layout="classic",
        terms_days=30,
        country_of_origin="US",
        catalog=[
            CatalogItem("HMK-MUG", "Stoneware mug, made in USA", D("30.00"), False, country="US", hts="69"),
            CatalogItem("HMK-CAR", "Glass carafe, made in USA", D("40.00"), False, country="US", hts="70"),
        ],
    ),
    "level": Supplier(
        key="level",
        name="Level Pantry",
        prefix="LVP",
        address=["220 Market Street", "Oakland, CA 94607"],
        email="ap@levelpantry.example",
        phone="(510) 555-0181",
        layout="classic",
        terms_days=30,
        country_of_origin="CN",
        catalog=[
            CatalogItem("LVP-NAP", "Dispenser napkin, 1-ply (case of 6000)", D("20.00"), True, country="CN", hts="48"),
            CatalogItem("LVP-TWL", "Bar towel, domestic (dozen)", D("15.00"), False, country="US", hts="63"),
        ],
    ),
    "calendar": Supplier(
        key="calendar",
        name="Calendar Imports",
        prefix="CIM",
        address=["9 Wharf Lane", "Alameda, CA 94501"],
        email="billing@calendarimports.example",
        phone="(510) 555-0144",
        layout="classic",
        terms_days=30,
        country_of_origin="IT",
        catalog=[
            CatalogItem("CIM-GSK", "Group head gasket, pack of 10 (Italy)", D("100.00"), True, country="IT", hts="84"),
            CatalogItem("CIM-TAMP", "Tamper, made in USA", D("40.00"), False, country="US", hts="82"),
        ],
    ),
    "mekong": Supplier(
        key="mekong",
        name="Mekong Tabletop",
        prefix="MKT",
        address=["501 International Blvd", "Oakland, CA 94606"],
        email="ar@mekongtabletop.example",
        phone="(510) 555-0190",
        layout="classic",
        terms_days=30,
        country_of_origin="VN",
        catalog=[
            CatalogItem("MKT-CUP", "Stoneware cup (Vietnam)", D("40.00"), True, country="VN", hts="69"),
            CatalogItem("MKT-TWL", "Bar towel, made in USA", D("18.00"), False, country="US", hts="63"),
        ],
    ),
    "guesswork": Supplier(
        key="guesswork",
        name="Guesswork Goods",
        prefix="GWG",
        address=["77 Broadway", "Oakland, CA 94607"],
        email="ap@guessworkgoods.example",
        phone="(510) 555-0128",
        layout="classic",
        terms_days=30,
        country_of_origin="IT",
        catalog=[
            CatalogItem("GWG-HEAD", "Espresso group head, origin not printed", D("200.00"), True, omit_origin=True, omit_hts=True),
            CatalogItem("GWG-TAMP", "Calibrated tamper, made in USA", D("48.00"), False, country="US", hts="82"),
        ],
    ),
    "clearpour": Supplier(
        key="clearpour",
        name="Clearpour Glass",
        prefix="CPG",
        address=["14 Vine Street", "Napa, CA 94559"],
        email="ap@clearpourglass.example",
        phone="(707) 555-0148",
        layout="classic",
        terms_days=30,
        country_of_origin="IT",
        catalog=[
            CatalogItem("CPG-CAR", "Glass carafe, Italy", D("80.00"), True, country="IT", hts="70"),
        ],
    ),
    "orchard": Supplier(
        key="orchard",
        name="Orchard Copper",
        prefix="ORC",
        address=["300 River Street", "Santa Rosa, CA 95401"],
        email="billing@orchardcopper.example",
        phone="(707) 555-0194",
        layout="classic",
        terms_days=30,
        country_of_origin="VN",
        catalog=[
            CatalogItem("ORC-PAN", "Copper saucepan, Vietnam", D("100.00"), True, country="VN", hts="74"),
        ],
    ),
}

# Northwind's November 2025 holiday stock-up: enough lines to force a 2nd page.
NORTHWIND_HOLIDAY_LINES = [
    ("NWP-HCUP08", "8 oz holiday hot cup, red snowflake (case of 500)", D("58.00")),
    ("NWP-HCUP12", "12 oz holiday hot cup, red snowflake (case of 500)", D("64.50")),
    ("NWP-HCUP16", "16 oz holiday hot cup, red snowflake (case of 500)", D("71.00")),
    ("NWP-HCUP20", "20 oz holiday hot cup, red snowflake (case of 500)", D("76.25")),
    ("NWP-HLID08", "Sip lid, white, fits 8 oz (case of 1000)", D("39.00")),
    ("NWP-HLID16", "Sip lid, white, fits 12/16 oz (case of 1000)", D("42.25")),
    ("NWP-HLID20", "Sip lid, white, fits 20 oz (case of 1000)", D("44.75")),
    ("NWP-HSLV", "Holiday cup sleeve, green print (case of 1000)", D("41.00")),
    ("NWP-CCUP12", "12 oz cold cup, clear PET (case of 1000)", D("88.00")),
    ("NWP-CCUP16", "16 oz cold cup, clear PET (case of 1000)", D("96.50")),
    ("NWP-CCUP24", "24 oz cold cup, clear PET (case of 600)", D("79.00")),
    ("NWP-CLIDF", "Flat cold lid, clear (case of 1000)", D("37.50")),
    ("NWP-CLIDD", "Dome cold lid, clear (case of 1000)", D("40.00")),
    ("NWP-BAG2", "Kraft takeout bag #2 (bundle of 500)", D("24.50")),
    ("NWP-BAG4", "Kraft takeout bag #4 (bundle of 500)", D("29.75")),
    ("NWP-BAG8", "Kraft takeout bag #8 (bundle of 250)", D("31.00")),
    ("NWP-BOX6", "Pastry box 6 x 6 x 3, kraft (case of 200)", D("46.00")),
    ("NWP-BOX9", "Pastry box 9 x 9 x 4, kraft (case of 100)", D("52.00")),
    ("NWP-TIS", "Bakery tissue 12 x 12 (case of 10000)", D("33.00")),
    ("NWP-NAP", "Dispenser napkins, 1-ply (case of 6000)", D("44.10")),
    ("NWP-NAPH", "Holiday beverage napkins, printed (case of 3000)", D("49.00")),
    ("NWP-STRAW", "Paper straws 7.75 in (case of 2400)", D("33.60")),
    ("NWP-STIR", "Wood stir sticks 7 in (case of 10000)", D("27.00")),
    ("NWP-SLV", "Corrugated cup sleeve, printed (case of 1000)", D("38.90")),
    ("NWP-TRAY", "4-cup carrier tray, molded fiber (case of 300)", D("42.00")),
    ("NWP-GIFT", "Gift card sleeve, foil stamped (case of 1000)", D("61.00")),
    ("NWP-TAPE", "Printed packing tape 2 in (case of 36)", D("54.00")),
    ("NWP-LABEL", "Round seal labels 2 in (roll of 1000)", D("12.40")),
]

# Which invoices are rendered as scans (OCR-only text).
SCANNED = {("NWP", 2025, 6), ("ALT", 2025, 8), ("KST", 2025, 10)}


# --------------------------------------------------------------------------- #
# Invoice generation
# --------------------------------------------------------------------------- #


class Generator:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)
        # One stream per supplier so tuning one supplier's quantities never
        # shifts another supplier's draws.
        self.supplier_rng = {key: random.Random(f"{seed}:{key}") for key in SUPPLIERS}
        self.counters: dict[str, int] = {}
        self.invoices: list[Invoice] = []
        self.credit_memos: list[Invoice] = []
        for s in SUPPLIERS.values():
            s.id = self.ramp_id("ven")
        self.catalog_index = {(s.key, item.sku): item for s in SUPPLIERS.values() for item in s.catalog}

    def ramp_id(self, kind: str) -> str:
        return f"{kind}_{self.rng.getrandbits(64):016x}"

    def next_number(self, supplier: Supplier, issued: date, kind: str = "invoice") -> str:
        key = f"{supplier.prefix}:{kind}"
        self.counters[key] = self.counters.get(key, 0) + 1
        infix = "-CM" if kind == "credit_memo" else ""
        return f"{supplier.prefix}{infix}-{issued:%Y%m}-{self.counters[key]:03d}"

    def pick_items(self, supplier: Supplier, k_min: int, k_max: int) -> list[CatalogItem]:
        rng = self.supplier_rng[supplier.key]
        k = rng.randint(k_min, min(k_max, len(supplier.catalog)))
        return rng.sample(supplier.catalog, k)

    def add(self, inv: Invoice):
        self._stamp(inv)
        inv.id = self.ramp_id("bill")
        inv.scanned = (inv.supplier.prefix, inv.issued.year, inv.issued.month) in SCANNED
        self.invoices.append(inv)

    def _stamp(self, inv: Invoice) -> None:
        """Put country and HTS on product lines. An omitted origin stays blank."""
        from pipeline.product_facts import resolve_hts

        for line in inv.lines:
            if line.category != PRODUCT:
                continue
            item = self.catalog_index.get((inv.supplier.key, line.sku))
            if item and item.omit_origin:
                line.country = None
            elif line.country is None:
                if item and item.country:
                    line.country = item.country
                elif item and not item.imported:
                    line.country = "US"
                else:
                    line.country = inv.supplier.country_of_origin
            if item and item.omit_hts:
                line.hts = None
            elif line.hts is None:
                stated = item.hts if item and item.hts else None
                chapter, _inferred = resolve_hts(stated, line.sku, line.description)
                line.hts = chapter

    # -- 1. Northwind -------------------------------------------------------- #
    def northwind(self):
        s = SUPPLIERS["northwind"]
        rng = self.supplier_rng["northwind"]
        for year, month in month_range(*INVOICE_RANGE):
            issued = date(year, month, 10)
            lines: list[Line] = []
            if (year, month) == (2025, 11):
                for sku, desc, price in NORTHWIND_HOLIDAY_LINES:
                    qty = Decimal(rng.randint(2, 10))
                    lines.append(Line(sku, desc, qty, price, PRODUCT))
            else:
                for item in self.pick_items(s, 4, 6):
                    qty = Decimal(rng.randint(5, 21))
                    lines.append(Line(item.sku, item.description, qty, item.base_price, PRODUCT))
            product_subtotal = sum((l.amount for l in lines), Decimal("0"))
            if date(2025, 4, 1) <= issued <= TARIFF_WINDOW_END:
                lines.append(
                    Line("SURCHG", "Tariff Surcharge (12%)", Decimal("1"), money(product_subtotal * D("0.12")), TARIFF_IEEPA)
                )
            lines.append(Line("FREIGHT", "Freight - LTL ground", Decimal("1"), money(rng.uniform(85, 180)), FREIGHT))
            self.add(Invoice(s, self.next_number(s, issued), issued, lines))

        # Credit memo, Mar 2026, partial credit against tariff surcharges.
        issued = date(2026, 3, 6)
        memo = Invoice(
            s,
            self.next_number(s, issued, "credit_memo"),
            issued,
            [Line("CREDIT", "Credit - partial refund of tariff surcharges billed Apr 2025 to Feb 2026", Decimal("1"), D("-500.00"), TARIFF_IEEPA)],
            kind="credit_memo",
            memo="Goodwill credit toward IEEPA tariff surcharges pending Supplier's duty refund. Apply to next open invoice.",
            reference="Tariff Surcharge (12%) lines on NWP invoices Apr 2025 - Feb 2026",
        )
        memo.id = self.ramp_id("vc")
        self.credit_memos.append(memo)

    # -- 2. Harbor & Pine ------------------------------------------------------ #
    def harborpine(self):
        # Italy's IEEPA tariff starts April 5, 2025 at 10%. The jump starts May 15
        # (40 days later) at 5%, inside the 6% cap (10% x 0.6). Domestic tools rise
        # 1% over the same months, so the claim is the 4-point gap, not the raw 5%.
        s = SUPPLIERS["harborpine"]
        rng = self.supplier_rng["harborpine"]
        inflated_from, inflated_to = date(2025, 5, 15), date(2026, 2, 20)
        controls = {"HP-TAMP", "HP-PITCH"}
        for year, month in month_range((2024, 7), INVOICE_RANGE[1], step=2):
            issued = date(year, month, 15)
            lines: list[Line] = []
            for item in s.catalog:
                if item.sku == "HP-SVC":
                    qty = Decimal(rng.randint(4, 12))
                elif item.base_price >= D("500"):
                    qty = Decimal(rng.randint(1, 5))
                else:
                    qty = Decimal(rng.randint(3, 12))
                if item.sku in controls and inflated_from <= issued <= inflated_to:
                    price = money(item.base_price * D("1.01"))
                    lines.append(Line(item.sku, item.description, qty, price, PRODUCT))
                elif item.imported and inflated_from <= issued <= inflated_to:
                    price = money(item.base_price * D("1.05"))
                    lines.append(Line(item.sku, item.description, qty, price, PRODUCT, baseline_unit_price=item.base_price))
                else:
                    lines.append(Line(item.sku, item.description, qty, item.base_price, PRODUCT))
            lines.append(Line("FREIGHT", "Shipping & handling", Decimal("1"), money(rng.uniform(35, 90)), FREIGHT))
            self.add(Invoice(s, self.next_number(s, issued), issued, lines))

    # -- 3. Altamesa ----------------------------------------------------------- #
    def altamesa(self):
        s = SUPPLIERS["altamesa"]
        rng = self.supplier_rng["altamesa"]
        for year, month in month_range((2024, 8), INVOICE_RANGE[1], step=2):
            issued = date(year, month, 12)
            lines: list[Line] = []
            for item in self.pick_items(s, 3, 5):
                qty = Decimal(rng.randint(2, 13))
                lines.append(Line(item.sku, item.description, qty, item.base_price, PRODUCT))
            product_subtotal = sum((l.amount for l in lines), Decimal("0"))
            if date(2025, 3, 1) <= issued <= TARIFF_WINDOW_END:
                label = "IEEPA Adj." if issued >= date(2025, 9, 1) else "Import Cost Recovery"
                lines.append(Line("ADJ", label, Decimal("1"), money(product_subtotal * D("0.20")), TARIFF_IEEPA))
            lines.append(Line("SHIP", "Ground shipping", Decimal("1"), money(rng.uniform(18, 60)), FREIGHT))
            self.add(Invoice(s, self.next_number(s, issued), issued, lines))

    # -- 4. Kestrel ------------------------------------------------------------ #
    def kestrel(self):
        s = SUPPLIERS["kestrel"]
        rng = self.supplier_rng["kestrel"]
        for year, month in month_range((2024, 7), INVOICE_RANGE[1], step=3):
            issued = date(year, month, 5)
            lines: list[Line] = []
            for item in self.pick_items(s, 2, 4):
                qty = Decimal(rng.randint(6, 40))
                lines.append(Line(item.sku, item.description, qty, item.base_price, PRODUCT))
            product_subtotal = sum((l.amount for l in lines), Decimal("0"))
            if issued >= date(2025, 5, 1):
                lines.append(Line("S301", "Section 301 adjustment", Decimal("1"), money(product_subtotal * D("0.075")), TARIFF_OTHER))
            lines.append(Line("FREIGHT", "Freight", Decimal("1"), money(rng.uniform(40, 110)), FREIGHT))
            self.add(Invoice(s, self.next_number(s, issued), issued, lines))

    # -- 5. Brightline --------------------------------------------------------- #
    def brightline(self):
        s = SUPPLIERS["brightline"]
        rng = self.supplier_rng["brightline"]
        start = date(2024, 7, 20)
        for year, month in month_range(*INVOICE_RANGE):
            issued = date(year, month, 20)
            years = Decimal((issued - start).days) / Decimal(365)
            drift = Decimal("1") + D("0.02") * years
            lines: list[Line] = []
            for item in self.pick_items(s, 3, 5):
                qty = Decimal(rng.randint(1, 10))
                lines.append(Line(item.sku, item.description, qty, money(item.base_price * drift), PRODUCT))
            lines.append(Line("FUEL", "Fuel surcharge", Decimal("1"), D("6.50"), OTHER_FEE))
            self.add(Invoice(s, self.next_number(s, issued), issued, lines))

    # -- 6. Pacific Freight ---------------------------------------------------- #
    def pacific(self):
        s = SUPPLIERS["pacific"]
        shipments = [
            (date(2025, 4, 18), "PFF-SH-88213", "231-4471022-5", D("2850.00"), D("1184.60")),
            (date(2025, 10, 7), "PFF-SH-91077", "231-4518860-1", D("3120.00"), D("1412.95")),
        ]
        for issued, bol, entry, freight, duty in shipments:
            lines = [
                Line("OFRT", f"Ocean freight, 20 ft container, Shanghai to Oakland (B/L {bol})", Decimal("1"), freight, FREIGHT),
                Line("DUTY", f"Customs duty paid on entry - Entry No. {entry} (IEEPA, China origin), importer of record: {BUYER['name']}", Decimal("1"), duty, CUSTOMS_DUTY_PAID_BY_BUYER),
                Line("BRKG", "Customs brokerage fee", Decimal("1"), D("185.00"), OTHER_FEE),
            ]
            self.add(Invoice(s, self.next_number(s, issued), issued, lines))

    def scripted(self, key: str, issued: date, goods: list[tuple[str, str, str]], extras: list[Line] | None = None):
        """One invoice. goods is (sku, qty, unit price). Country and HTS come from the catalog."""
        supplier = SUPPLIERS[key]
        by_sku = {item.sku: item for item in supplier.catalog}
        lines: list[Line] = []
        for sku, qty, price in goods:
            item = by_sku[sku]
            lines.append(Line(sku, item.description, Decimal(qty), D(price), PRODUCT))
        lines.extend(extras or [])
        lines.append(Line("FREIGHT", "Freight", Decimal("1"), D("25.00"), FREIGHT))
        self.add(Invoice(supplier, self.next_number(supplier, issued), issued, lines))

    def lumen(self):
        # Surcharge wording the keyword rules miss. The answer key still calls them IEEPA.
        hidden = [
            (date(2025, 6, 15), "Q3 landed cost adjustment", "420.00"),
            (date(2025, 9, 15), "Supplier cost pass-through", "310.00"),
            (date(2025, 12, 15), "Global sourcing fee", "275.00"),
        ]
        self.scripted("lumen", date(2024, 11, 10), [("LUM-CUP", "10", "40.00")])
        for issued, label, amount in hidden:
            self.scripted(
                "lumen",
                issued,
                [("LUM-CUP", "10", "40.00")],
                [Line("ADJ", label, Decimal("1"), D(amount), TARIFF_IEEPA, keyword_hidden=True)],
            )

    def mill(self):
        self.scripted(
            "mill",
            date(2025, 6, 1),
            [("MLA-SHT", "4", "180.00")],
            [Line("S232", "Section 232 steel and aluminum surcharge", Decimal("1"), D("640.00"), TARIFF_OTHER)],
        )

    def early(self):
        # China tariff date is February 4, 2025. This jump starts November 2024.
        self.scripted("early", date(2024, 8, 10), [("ERP-CUP", "10", "40.00"), ("ERP-DOM", "8", "12.00")])
        self.scripted("early", date(2024, 10, 10), [("ERP-CUP", "10", "40.00"), ("ERP-DOM", "8", "12.00")])
        self.scripted("early", date(2024, 11, 15), [("ERP-CUP", "10", "44.00"), ("ERP-DOM", "8", "12.00")])
        self.scripted("early", date(2025, 5, 10), [("ERP-CUP", "10", "44.00"), ("ERP-DOM", "8", "12.00")])

    def homestead(self):
        # The carafe is domestic and rises 4% on May 20. It is the category control for Clearpour.
        self.scripted("homestead", date(2024, 9, 1), [("HMK-MUG", "12", "30.00"), ("HMK-CAR", "6", "40.00")])
        self.scripted("homestead", date(2025, 1, 15), [("HMK-MUG", "12", "30.00"), ("HMK-CAR", "6", "40.00")])
        self.scripted("homestead", date(2025, 5, 20), [("HMK-MUG", "12", "33.60"), ("HMK-CAR", "6", "41.60")])
        self.scripted("homestead", date(2025, 11, 20), [("HMK-MUG", "12", "33.60"), ("HMK-CAR", "6", "41.60")])

    def level(self):
        # Both the imported napkin and the domestic towel rise 4% on March 15, 2025.
        base = [("LVP-NAP", "20", "20.00"), ("LVP-TWL", "10", "15.00")]
        up = [("LVP-NAP", "20", "20.80"), ("LVP-TWL", "10", "15.60")]
        self.scripted("level", date(2024, 8, 1), base)
        self.scripted("level", date(2024, 11, 1), base)
        self.scripted("level", date(2025, 1, 10), base)
        self.scripted("level", date(2025, 3, 15), up)
        self.scripted("level", date(2025, 10, 12), up)

    def calendar(self):
        # Italy's tariff date is April 5. This jump starts March 4, the Canada/Mexico date.
        base = [("CIM-GSK", "6", "100.00"), ("CIM-TAMP", "4", "40.00")]
        up = [("CIM-GSK", "6", "105.00"), ("CIM-TAMP", "4", "40.00")]
        self.scripted("calendar", date(2024, 8, 4), base)
        self.scripted("calendar", date(2024, 11, 4), base)
        self.scripted("calendar", date(2025, 3, 4), up)
        self.scripted("calendar", date(2025, 7, 4), up)

    def mekong(self):
        # Vietnam's country rate starts August 7, 2025 at 20%. The jump starts September 1,
        # 25 days later. April 5 is outside the 90-day window, so this counts only because
        # a later rate increase qualifies. The US towel stays flat.
        base = [("MKT-CUP", "8", "40.00"), ("MKT-TWL", "6", "18.00")]
        up = [("MKT-CUP", "8", "42.00"), ("MKT-TWL", "6", "18.00")]
        self.scripted("mekong", date(2024, 9, 1), base)
        self.scripted("mekong", date(2025, 1, 15), base)
        self.scripted("mekong", date(2025, 6, 1), base)
        self.scripted("mekong", date(2025, 9, 1), up)
        self.scripted("mekong", date(2025, 12, 1), up)
        self.scripted("mekong", date(2026, 3, 15), base)

    def clearpour(self):
        # No domestic SKU. Homestead's US carafe, same category, rises 4% on the same day.
        # This carafe rises 5.5%. The gap is 1.5 points, inside the 2-point band, so it does not count.
        base = [("CPG-CAR", "5", "80.00")]
        up = [("CPG-CAR", "5", "84.40")]
        self.scripted("clearpour", date(2024, 10, 1), base)
        self.scripted("clearpour", date(2025, 1, 10), base)
        self.scripted("clearpour", date(2025, 5, 20), up)
        self.scripted("clearpour", date(2025, 9, 20), up)
        self.scripted("clearpour", date(2025, 12, 15), up)

    def orchard(self):
        # Vietnam's August 7 rate. The jump is September 10, 34 days later. Nothing else
        # in the dataset is copper cookware, so there is no control group.
        base = [("ORC-PAN", "4", "100.00")]
        up = [("ORC-PAN", "4", "106.00")]
        self.scripted("orchard", date(2024, 11, 1), base)
        self.scripted("orchard", date(2025, 4, 1), base)
        self.scripted("orchard", date(2025, 9, 10), up)
        self.scripted("orchard", date(2025, 12, 10), up)

    def guesswork(self):
        # Origin is not on the invoice. The suggestion is inferred, so strength stays Low.
        base = [("GWG-HEAD", "2", "200.00"), ("GWG-TAMP", "4", "48.00")]
        up = [("GWG-HEAD", "2", "210.00"), ("GWG-TAMP", "4", "48.00")]
        self.scripted("guesswork", date(2024, 9, 20), base)
        self.scripted("guesswork", date(2025, 1, 20), base)
        self.scripted("guesswork", date(2025, 5, 20), up)
        self.scripted("guesswork", date(2025, 10, 20), up)
        self.scripted("guesswork", date(2026, 3, 20), base)

    def run(self):
        self.northwind()
        self.harborpine()
        self.altamesa()
        self.kestrel()
        self.brightline()
        self.pacific()
        self.lumen()
        self.mill()
        self.early()
        self.homestead()
        self.level()
        self.calendar()
        self.mekong()
        self.guesswork()
        self.clearpour()
        self.orchard()
        self.invoices.sort(key=lambda i: (i.issued, i.number))


# --------------------------------------------------------------------------- #
# PDF rendering: three layouts
# --------------------------------------------------------------------------- #

PAGE_W, PAGE_H = LETTER


def styles(font: str, bold: str) -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName=font, fontSize=9, leading=11.5)
    return {
        "base": base,
        "small": ParagraphStyle("small", parent=base, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#555555")),
        "bold": ParagraphStyle("bold", parent=base, fontName=bold),
        "right": ParagraphStyle("right", parent=base, alignment=TA_RIGHT),
        "title": ParagraphStyle("title", parent=base, fontName=bold, fontSize=20, leading=24),
        "title_center": ParagraphStyle("title_center", parent=base, fontName=bold, fontSize=18, leading=22, alignment=TA_CENTER),
        "h": ParagraphStyle("h", parent=base, fontName=bold, fontSize=11, leading=14),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.5, leading=10.5),
        "cell_right": ParagraphStyle("cell_right", parent=base, fontSize=8.5, leading=10.5, alignment=TA_RIGHT),
        "white": ParagraphStyle("white", parent=base, fontName=bold, fontSize=16, leading=20, textColor=colors.white),
        "white_small": ParagraphStyle("white_small", parent=base, fontSize=8.5, leading=11, textColor=colors.white),
    }


def bill_to_paragraph(st) -> Paragraph:
    return Paragraph(
        f"<b>Bill to</b><br/>{BUYER['name']}<br/>{BUYER['attn']}<br/>{BUYER['address_line1']}<br/>{BUYER['address_line2']}",
        st["base"],
    )


def doc_title(inv: Invoice) -> str:
    return "CREDIT MEMO" if inv.kind == "credit_memo" else "INVOICE"


def line_table(inv: Invoice, columns: list[str], st, font: str, bold: str, header_bg, zebra=True) -> Table:
    """columns: subset/order of sku, description, qty, unit_price, amount."""
    header_labels = {"sku": "SKU", "description": "Description", "qty": "Qty", "unit_price": "Unit price", "amount": "Amount"}
    widths = {"sku": 1.0 * inch, "description": 3.3 * inch, "qty": 0.6 * inch, "unit_price": 1.0 * inch, "amount": 1.1 * inch}
    numeric = {"qty", "unit_price", "amount"}

    rows = [[header_labels[c] for c in columns]]
    for l in inv.lines:
        row = []
        for c in columns:
            if c == "sku":
                row.append(Paragraph(l.sku, st["cell"]))
            elif c == "description":
                row.append(Paragraph(l.description, st["cell"]))
            elif c == "qty":
                row.append(Paragraph(f"{l.qty:,.0f}", st["cell_right"]))
            elif c == "unit_price":
                row.append(Paragraph(fmt(l.unit_price), st["cell_right"]))
            else:
                row.append(Paragraph(fmt(l.amount), st["cell_right"]))
        rows.append(row)

    t = Table(rows, colWidths=[widths[c] for c in columns], repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, 0), bold),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for idx, c in enumerate(columns):
        if c in numeric:
            style.append(("ALIGN", (idx, 0), (idx, -1), "RIGHT"))
    if zebra:
        style.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f4f2")]))
    else:
        style.append(("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#bbbbbb")))
    t.setStyle(TableStyle(style))
    return t


def totals_table(inv: Invoice, st, bold: str) -> Table:
    non_product = [l for l in inv.lines if l.category != PRODUCT]
    rows = [["Subtotal (products)", fmt(inv.product_subtotal)]]
    for l in non_product:
        rows.append([Paragraph(l.description, st["cell"]), fmt(l.amount)])
    rows.append([f"Sales tax ({TAX_RATE * 100:.2f}%)", fmt(inv.tax)])
    rows.append([("Credit total" if inv.kind == "credit_memo" else "Total due"), fmt(inv.total)])
    t = Table(rows, colWidths=[2.4 * inch, 1.3 * inch], hAlign="RIGHT")
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), bold),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return t


def meta_rows(inv: Invoice, st, align_right: bool = True) -> list[list]:
    value_style = st["cell_right"] if align_right else st["cell"]
    rows = [
        [f"{doc_title(inv).title()} no.", Paragraph(inv.number, value_style)],
        ["Date", Paragraph(f"{inv.issued:%b %d, %Y}", value_style)],
    ]
    if inv.kind == "invoice":
        rows.append(["Due date", Paragraph(f"{inv.due:%b %d, %Y}", value_style)])
        rows.append(["Terms", Paragraph(f"Net {inv.supplier.terms_days}", value_style)])
    else:
        rows.append(["Reference", Paragraph(inv.reference or "", value_style)])
    return rows


def footer_note(inv: Invoice, default: str) -> str:
    if inv.kind == "credit_memo":
        return f"This credit may be applied against any open or future invoice from {inv.supplier.name}. Questions: {inv.supplier.email}."
    return default


def layout_classic(inv: Invoice) -> list:
    """Helvetica. Supplier top-left, meta top-right, SKU-first table, zebra rows."""
    font, bold = "Helvetica", "Helvetica-Bold"
    st = styles(font, bold)
    s = inv.supplier
    supplier_block = Paragraph(
        f"<font size=14><b>{s.name}</b></font><br/>{s.address[0]}<br/>{s.address[1]}<br/>{s.phone} &nbsp;|&nbsp; {s.email}",
        st["base"],
    )
    meta = Table(meta_rows(inv, st), colWidths=[1.0 * inch, 1.8 * inch], hAlign="RIGHT")
    meta.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("FONTNAME", (0, 0), (0, -1), bold), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    header = Table([[supplier_block, [Paragraph(doc_title(inv), st["title"]), Spacer(1, 6), meta]]], colWidths=[4.2 * inch, 2.8 * inch])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    story = [header, Spacer(1, 18), bill_to_paragraph(st), Spacer(1, 16)]
    if inv.memo:
        story += [Paragraph(inv.memo, st["base"]), Spacer(1, 10)]
    story.append(line_table(inv, ["sku", "description", "qty", "unit_price", "amount"], st, font, bold, colors.HexColor("#e8e8e4")))
    story += [Spacer(1, 12), totals_table(inv, st, bold), Spacer(1, 24)]
    story.append(Paragraph(footer_note(inv, f"Please remit to {s.name}, {s.address[0]}, {s.address[1]}. Questions: {s.email}."), st["small"]))
    return story


def layout_ledger(inv: Invoice) -> list:
    """Times-Roman. Centered supplier name, boxed meta, description-first table, ruled rows."""
    font, bold = "Times-Roman", "Times-Bold"
    st = styles(font, bold)
    s = inv.supplier
    story = [
        Paragraph(s.name.upper(), st["title_center"]),
        Paragraph(f"{s.address[0]} &middot; {s.address[1]} &middot; {s.phone}", ParagraphStyle("c", parent=st["small"], alignment=TA_CENTER)),
        Spacer(1, 14),
    ]
    meta = Table(meta_rows(inv, st, align_right=False), colWidths=[1.1 * inch, 1.7 * inch])
    meta.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.75, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#999999")),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 0), (0, -1), bold),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0ede6")),
            ]
        )
    )
    header = Table([[[Paragraph(doc_title(inv), st["h"]), Spacer(1, 6), bill_to_paragraph(st)], meta]], colWidths=[4.2 * inch, 2.8 * inch])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    story += [header, Spacer(1, 18)]
    if inv.memo:
        story += [Paragraph(inv.memo, st["base"]), Spacer(1, 10)]
    story.append(line_table(inv, ["description", "sku", "qty", "unit_price", "amount"], st, font, bold, colors.white, zebra=False))
    story += [Spacer(1, 12), totals_table(inv, st, bold), Spacer(1, 24)]
    story.append(Paragraph(footer_note(inv, f"Terms: Net {s.terms_days}. Remit payment to {s.name}. Thank you for your business."), st["small"]))
    return story


def layout_mono(inv: Invoice) -> list:
    """Courier. Dark header band, meta on the left, qty-first table."""
    font, bold = "Courier", "Courier-Bold"
    st = styles(font, bold)
    s = inv.supplier
    band = Table(
        [[Paragraph(s.name, st["white"]), Paragraph(f"{doc_title(inv)}<br/>{inv.number}", ParagraphStyle("wr", parent=st["white_small"], alignment=TA_RIGHT))]],
        colWidths=[4.6 * inch, 2.4 * inch],
    )
    band.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1f2326")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    meta = Table(meta_rows(inv, st, align_right=False), colWidths=[1.1 * inch, 1.9 * inch], hAlign="LEFT")
    meta.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8.5), ("FONTNAME", (0, 0), (0, -1), bold), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    from_block = Paragraph(f"<b>From</b><br/>{s.name}<br/>{s.address[0]}<br/>{s.address[1]}<br/>{s.email}", st["base"])
    header = Table([[meta, from_block, bill_to_paragraph(st)]], colWidths=[2.5 * inch, 2.5 * inch, 2.0 * inch])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, 0), 0)]))
    story = [band, Spacer(1, 14), header, Spacer(1, 16)]
    if inv.memo:
        story += [Paragraph(inv.memo, st["base"]), Spacer(1, 10)]
    story.append(line_table(inv, ["qty", "sku", "description", "unit_price", "amount"], st, font, bold, colors.HexColor("#dcdcdc")))
    story += [Spacer(1, 12), totals_table(inv, st, bold), Spacer(1, 24)]
    story.append(Paragraph(footer_note(inv, f"ACH and check accepted. Reference {inv.number} on all payments. {s.phone}"), st["small"]))
    return story


LAYOUTS = {"classic": layout_classic, "ledger": layout_ledger, "mono": layout_mono}


def render_pdf(inv: Invoice) -> bytes:
    buf = io.BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawRightString(PAGE_W - 0.75 * inch, 0.5 * inch, f"{inv.number}  |  Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.8 * inch,
        title=f"{doc_title(inv).title()} {inv.number}",
        author=inv.supplier.name,
    )
    doc.build(LAYOUTS[inv.supplier.layout](inv), onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def scanify(pdf_bytes: bytes, rng: random.Random, np_rng: np.random.Generator) -> bytes:
    """Rasterize, rotate 1-2 degrees, blur, add noise, re-save as an image-only PDF."""
    dpi = 150
    pdf = pdfium.PdfDocument(pdf_bytes)
    pages: list[Image.Image] = []
    angle = rng.choice([-1, 1]) * rng.uniform(1.0, 2.0)
    for page in pdf:
        img = page.render(scale=dpi / 72).to_pil().convert("L")
        w, h = img.size
        img = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=235)
        # Crop back to the original size so the page edge shows as a skewed border.
        left = (img.width - w) // 2
        top = (img.height - h) // 2
        img = img.crop((left, top, left + w, top + h))
        img = img.filter(ImageFilter.GaussianBlur(radius=0.7))
        arr = np.asarray(img, dtype=np.float32)
        arr = arr * 0.94 + 8  # slightly gray paper, lower contrast
        arr += np_rng.normal(0, 7, arr.shape)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "L")
        pages.append(img)
    out = io.BytesIO()
    fixed_ts = time.gmtime(1771588800)  # 2026-02-20T12:00Z; keeps bytes deterministic
    pages[0].save(
        out, "PDF", save_all=True, append_images=pages[1:], resolution=dpi,
        creationDate=fixed_ts, modDate=fixed_ts, producer="scanner",
    )
    return out.getvalue()


def page_count(pdf_bytes: bytes) -> int:
    return len(pdfium.PdfDocument(pdf_bytes))


# --------------------------------------------------------------------------- #
# Contracts
# --------------------------------------------------------------------------- #

CONTRACT_COMMON = [
    ("1. Term", "This Agreement commences on the Effective Date and continues for twenty-four (24) months, renewing automatically for successive twelve (12) month periods unless either party gives sixty (60) days written notice of non-renewal."),
    ("2. Orders", "Buyer may order Products by purchase order referencing this Agreement. Each accepted purchase order is governed exclusively by this Agreement, and any conflicting terms on Supplier's acknowledgments or invoices are rejected."),
    ("3. Pricing and Payment", "Prices are as set forth in Supplier's then-current price list provided to Buyer. Supplier shall invoice upon shipment. Invoices are payable within the net terms stated on the invoice. Buyer may offset undisputed credits owed by Supplier against amounts due."),
    ("4. Delivery", "Supplier shall deliver Products FOB Buyer's facility at 1820 Shattuck Ave, Berkeley, CA 94709 unless otherwise agreed. Freight charges, if any, shall be separately itemized on the invoice."),
    ("5. Warranty", "Supplier warrants that Products conform to specifications and are free from defects in materials and workmanship for twelve (12) months from delivery."),
]

CONTRACT_TARIFF_CLAUSES = {
    "northwind": (
        "7. Duties, Tariffs and Surcharges",
        "Supplier may add a tariff surcharge to invoices to recover customs duties actually paid by Supplier on Products sold to Buyer. Any such surcharge shall be stated as a separate line item and shall not exceed the duty actually incurred. "
        "If any duty underlying a surcharge is subsequently refunded, remitted, reduced or otherwise recovered by Supplier, whether by administrative action, protest, litigation or otherwise, Supplier shall credit Buyer the corresponding surcharge amounts within sixty (60) days of Supplier's receipt of such refund. "
        "Credits shall be issued as vendor credits applied against Buyer's open or future invoices, or at Buyer's election, by payment.",
    ),
    "harborpine": (
        "6. Pricing; Import Duties",
        "Prices for imported Products are inclusive of customs duties, tariffs and similar import charges borne by Supplier. Supplier shall give Buyer thirty (30) days notice of any price change attributable to a change in such charges. "
        "In the event any duty, tariff or similar charge paid by Supplier with respect to Products sold to Buyer is refunded to Supplier by any governmental authority, Supplier shall pass through to Buyer a pro rata share of such refund attributable to Products purchased by Buyer during the period the charge was in effect, net of Supplier's reasonable documented costs of recovery, within ninety (90) days of receipt.",
    ),
}

CONTRACT_GENERIC_TAIL = [
    ("6. Confidentiality", "Each party shall keep the other's non-public business information confidential and use it only to perform this Agreement."),
    ("7. Limitation of Liability", "Neither party is liable for indirect, incidental or consequential damages arising out of this Agreement. Supplier's aggregate liability shall not exceed amounts paid by Buyer in the twelve (12) months preceding the claim."),
    ("8. Termination", "Either party may terminate this Agreement for material breach not cured within thirty (30) days of written notice."),
    ("9. Governing Law", "This Agreement is governed by the laws of the State of California without regard to its conflict of laws principles."),
]


def contract_sections(key: str) -> tuple[str, date, list[tuple[str, str]]]:
    if key == "northwind":
        title = "Supply Agreement"
        effective = date(2023, 9, 1)
        sections = CONTRACT_COMMON + [
            ("6. Confidentiality", CONTRACT_GENERIC_TAIL[0][1]),
            CONTRACT_TARIFF_CLAUSES["northwind"],
            ("8. Limitation of Liability", CONTRACT_GENERIC_TAIL[1][1]),
            ("9. Termination", CONTRACT_GENERIC_TAIL[2][1]),
            ("10. Governing Law", CONTRACT_GENERIC_TAIL[3][1]),
        ]
    elif key == "harborpine":
        title = "Equipment and Service Agreement"
        effective = date(2024, 2, 1)
        sections = CONTRACT_COMMON[:2] + [
            ("3. Service", "Supplier shall provide on-site espresso equipment service at Buyer's locations at the hourly rate in Supplier's price list, billed in half-hour increments."),
            ("4. Delivery", CONTRACT_COMMON[3][1]),
            ("5. Warranty", CONTRACT_COMMON[4][1]),
            CONTRACT_TARIFF_CLAUSES["harborpine"],
            ("7. Confidentiality", CONTRACT_GENERIC_TAIL[0][1]),
            ("8. Limitation of Liability", CONTRACT_GENERIC_TAIL[1][1]),
            ("9. Termination", CONTRACT_GENERIC_TAIL[2][1]),
            ("10. Governing Law", CONTRACT_GENERIC_TAIL[3][1]),
        ]
    elif key == "kestrel":
        title = "Master Supply Agreement"
        effective = date(2024, 1, 15)
        sections = CONTRACT_COMMON + CONTRACT_GENERIC_TAIL
    elif key == "brightline":
        title = "Office Supply Agreement"
        effective = date(2022, 6, 1)
        sections = CONTRACT_COMMON + CONTRACT_GENERIC_TAIL
    else:
        raise ValueError(key)
    return title, effective, sections


def render_contract(supplier: Supplier) -> tuple[bytes, dict]:
    title, effective, sections = contract_sections(supplier.key)
    st = styles("Times-Roman", "Times-Bold")
    body = ParagraphStyle("body", parent=st["base"], fontSize=10, leading=14, spaceAfter=8)
    heading = ParagraphStyle("heading", parent=st["base"], fontName="Times-Bold", fontSize=10.5, leading=14, spaceBefore=8, spaceAfter=2)
    story = [
        Paragraph(title.upper(), st["title_center"]),
        Spacer(1, 14),
        Paragraph(
            f"This {title} (the \"Agreement\") is entered into as of {effective:%B %d, %Y} (the \"Effective Date\") between "
            f"<b>{supplier.name}</b>, with offices at {supplier.address[0]}, {supplier.address[1]} (\"Supplier\"), and "
            f"<b>{BUYER['name']}</b>, with offices at {BUYER['address_line1']}, {BUYER['address_line2']} (\"Buyer\").",
            body,
        ),
        Paragraph("The parties agree as follows:", body),
    ]
    for head, text in sections:
        story += [Paragraph(head, heading), Paragraph(text, body)]
    story += [
        Spacer(1, 18),
        Paragraph("IN WITNESS WHEREOF, the parties have executed this Agreement as of the Effective Date.", body),
        Spacer(1, 24),
        Table(
            [
                [Paragraph(f"<b>{supplier.name}</b><br/><br/>By: ______________________<br/>Name: Jordan Reyes<br/>Title: VP, Sales", body),
                 Paragraph(f"<b>{BUYER['name']}</b><br/><br/>By: ______________________<br/>Name: Priya Natarajan<br/>Title: Controller", body)],
            ],
            colWidths=[3.5 * inch, 3.5 * inch],
        ),
    ]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=1 * inch, rightMargin=1 * inch, topMargin=1 * inch, bottomMargin=1 * inch, title=f"{title} - {supplier.name}")
    doc.build(story)
    tariff_clause = CONTRACT_TARIFF_CLAUSES.get(supplier.key)
    meta = {
        "title": title,
        "effective_date": effective.isoformat(),
        "has_tariff_clause": tariff_clause is not None,
        "tariff_clause_section": tariff_clause[0] if tariff_clause else None,
    }
    return buf.getvalue(), meta


# --------------------------------------------------------------------------- #
# Ground truth and exports
# --------------------------------------------------------------------------- #


def f2(d: Decimal) -> float:
    return float(money(d))


def _price_analysis(gen: Generator):
    """The same qualifier the pipeline uses, so the answer key cannot drift."""
    from pipeline.exposure import _match
    from pipeline.prices import Observation, qualify
    from pipeline.product_facts import resolve_hts, resolve_origin
    from pipeline.tariffs import DEFAULT_IMPORT_SHARE

    rows = []
    for inv in gen.invoices:
        for index, line in enumerate(inv.all_lines()):
            if line.category != PRODUCT:
                continue
            country, inferred = resolve_origin(line.country, line.description)
            hts, _hts_inferred = resolve_hts(line.hts, line.sku, line.description)
            rows.append(
                Observation(
                    vendor=inv.supplier.name,
                    sku=line.sku,
                    invoice_number=inv.number,
                    line_index=index,
                    issued=inv.issued,
                    description=line.description,
                    quantity=line.qty,
                    unit_price=line.unit_price,
                    country=country,
                    hts=hts,
                    origin_inferred=inferred,
                    import_cost_share=DEFAULT_IMPORT_SHARE,
                    category_id=_match(line.sku, line.description),
                    labeled_by="ground-truth",
                )
            )
    return qualify(rows)


def build_ground_truth(gen: Generator, contracts_meta: dict[str, dict]) -> dict:
    analysis = _price_analysis(gen)
    findings_by_vendor: dict[str, list] = {}
    for finding in analysis.findings:
        findings_by_vendor.setdefault(finding.vendor_name, []).append(finding)

    suppliers: dict[str, dict] = {}
    price_items = []
    for sku in analysis.skus:
        if not sku.qualified:
            continue
        price_items.append(
            {
                "vendor": sku.vendor_name,
                "sku": sku.sku,
                "origin_inferred": sku.origin_inferred,
                "country": sku.country,
                "low": f2(sku.claim_low),
                "expected": f2(sku.claim_expected),
                "high": f2(sku.claim_high),
            }
        )

    for s in SUPPLIERS.values():
        invs = [i for i in gen.invoices if i.supplier is s]
        explicit_ieepa = Decimal("0")
        hidden_ieepa = Decimal("0")
        non_refundable = Decimal("0")
        decoy_fees = Decimal("0")
        affected: list[dict] = []
        for inv in invs:
            if not (TARIFF_WINDOW_START <= inv.issued <= TARIFF_WINDOW_END):
                continue
            for line in inv.lines:
                if line.category == TARIFF_IEEPA:
                    explicit_ieepa += line.amount
                    if line.keyword_hidden:
                        hidden_ieepa += line.amount
                elif line.category == TARIFF_OTHER:
                    non_refundable += line.amount
                elif line.category == OTHER_FEE:
                    decoy_fees += line.amount
        price_findings = findings_by_vendor.get(s.name, [])
        price_low = sum((item.low_amount for item in price_findings), Decimal("0"))
        price_expected = sum((item.amount for item in price_findings), Decimal("0"))
        price_high = sum((item.high_amount for item in price_findings), Decimal("0"))
        if price_expected or explicit_ieepa or non_refundable:
            basis = "explicit_surcharge" if explicit_ieepa and not price_expected else (
                "embedded_price_increase" if price_expected else "non_ieepa_tariff"
            )
            if explicit_ieepa and price_expected:
                basis = "explicit_surcharge"
            affected.append({"basis": basis, "refundable_amount": f2(explicit_ieepa + price_expected)})
        credits = sum((-m.total for m in gen.credit_memos if m.supplier is s), Decimal("0"))
        refundable = explicit_ieepa + price_expected
        demo_refundable = refundable - hidden_ieepa
        if explicit_ieepa:
            basis = "explicit_surcharge"
        elif price_expected:
            basis = "embedded_price_increase"
        elif non_refundable:
            basis = "non_ieepa_tariff"
        else:
            basis = "none"
        suppliers[s.name] = {
            "vendor_id": s.id,
            "refundable_claim_total": f2(refundable),
            "demo_refundable_claim_total": f2(demo_refundable),
            "credits_already_received": f2(credits),
            "net_claim_total": f2(refundable - credits),
            "demo_net_claim_total": f2(demo_refundable - credits),
            "non_refundable_total": f2(non_refundable),
            "basis": basis,
            "explicit_surcharge_total": f2(explicit_ieepa),
            "keyword_hidden_ieepa": f2(hidden_ieepa),
            "raw_price_increase": f2(price_high),
            "conservative_claim": f2(price_expected),
            "claim_low": f2(price_low),
            "claim_expected": f2(price_expected),
            "claim_high": f2(price_high),
            "embedded_price_increase_total": f2(price_high),
            "decoy_fee_total": f2(decoy_fees),
            "invoice_count": len(invs),
            "invoices_affected": affected,
            "contract": contracts_meta.get(s.key),
            "notes": SUPPLIER_NOTES[s.key],
        }

    ior_cases = []
    for inv in gen.invoices:
        for l in inv.lines:
            if l.category == CUSTOMS_DUTY_PAID_BY_BUYER:
                entry = l.description.split("Entry No. ")[1].split(" ")[0]
                ior_cases.append(
                    {
                        "invoice_number": inv.number,
                        "vendor": inv.supplier.name,
                        "issued_at": inv.issued.isoformat(),
                        "entry_number": entry,
                        "customs_duty_paid": f2(l.amount),
                        "note": "Sunbird was importer of record. Refund comes from CBP via the entry, not from the supplier. Exclude from supplier claims.",
                    }
                )

    totals = {
        "refundable_claim_total": f2(sum(Decimal(str(v["refundable_claim_total"])) for v in suppliers.values())),
        "demo_refundable_claim_total": f2(sum(Decimal(str(v["demo_refundable_claim_total"])) for v in suppliers.values())),
        "raw_price_increase": f2(sum(Decimal(str(v["raw_price_increase"])) for v in suppliers.values())),
        "conservative_claim": f2(sum(Decimal(str(v["conservative_claim"])) for v in suppliers.values())),
        "net_claim_total_after_credits": f2(sum(Decimal(str(v["net_claim_total"])) for v in suppliers.values())),
        "demo_net_claim_total_after_credits": f2(sum(Decimal(str(v["demo_net_claim_total"])) for v in suppliers.values())),
        "non_refundable_total": f2(sum(Decimal(str(v["non_refundable_total"])) for v in suppliers.values())),
        "importer_of_record_duty_total": f2(sum(Decimal(str(c["customs_duty_paid"])) for c in ior_cases)),
        "price_claim_method": {
            "expected_claim": "explicit IEEPA lines plus the difference-in-differences price claim",
            "low": "half the difference-in-differences excess, a 50% pass-through",
            "high": "the raw unit-price jump over the pre-tariff price",
            "demo": "demo_refundable excludes surcharge lines whose wording the keyword rules miss",
        },
    }
    return {
        "buyer": BUYER,
        "tariff_window": {"start": TARIFF_WINDOW_START.isoformat(), "end": TARIFF_WINDOW_END.isoformat()},
        "amounts_are_pre_sales_tax": True,
        "price_claim_note": "refundable_claim_total is the full answer, including wording a keyword rule misses. demo_refundable_claim_total is what DEMO_MODE should recover. Price claims use the expected difference-in-differences amount. claim_low is half of that. claim_high is the raw jump.",
        "suppliers": suppliers,
        "price_items": price_items,
        "cases": BENCHMARK_CASES,
        "importer_of_record_cases": ior_cases,
        "totals": totals,
    }


SUPPLIER_NOTES = {
    "northwind": "Documented. Explicit 'Tariff Surcharge (12%)' from Apr 2025 to Feb 2026. Contract section 7 requires a credit if duties are refunded. $500 credit memo already issued Mar 2026.",
    "harborpine": "Contract + price. Italian parts rise 5% from May 15, 2025 (40 days after Italy's April 5 tariff) and revert in March 2026. Domestic tampers and pitchers rise 1% over the same months. The claim is the 4-point gap. Contract section 6 allows pass-through.",
    "altamesa": "Documented. 20% surcharge labeled 'Import Cost Recovery' then 'IEEPA Adj.' No contract on file.",
    "kestrel": "Section 301 adjustment from May 2025. Not IEEPA, not refundable.",
    "brightline": "Domestic. Prices drift about 2% a year. Fuel surcharge is not a tariff. Claim $0.",
    "pacific": "Sunbird was importer of record. Customs duty is owed by CBP, not this supplier. Claim $0.",
    "lumen": "Documented in the answer key, missed by demo keywords: 'Q3 landed cost adjustment', 'Supplier cost pass-through', 'Global sourcing fee'.",
    "mill": "Section 232 steel and aluminum surcharge. Not IEEPA, not refundable.",
    "early": "China origin, but the price jumped in November 2024, before the February 4, 2025 tariff. Does not count.",
    "homestead": "Made in the USA. A May 2025 mug increase does not count. The glass carafe rises 4% and is the category control for Clearpour Glass.",
    "level": "Imported and domestic goods both rise 4% on March 15, 2025. The control group moved with the item. Does not count.",
    "calendar": "Italian goods jump on March 4, 2025, the Canada and Mexico date, before Italy's April 5 date. Does not count.",
    "mekong": "Vietnamese goods stay flat through June 2025, then jump September 1, 25 days after the August 7 country rate. April 5 is outside the 90-day window. Price-only. Counts.",
    "guesswork": "Espresso group head with no country on the invoice. Origin is inferred, so the claim counts and strength is Low.",
    "clearpour": "Only an imported Italian carafe, so there is no in-house control. Homestead's US carafe, same category, rose 4% on the same day. This carafe rose 5.5%. The gap is 1.5 points, so it does not count.",
    "orchard": "Vietnamese copper saucepan jumps September 10, 2025, 34 days after Vietnam's August 7 rate. No other supplier sells this category. Needs review. Not claimed.",
}

BENCHMARK_CASES = [
    {"id": "wording", "vendor": "Lumen Sourcing Co.", "should_count": True, "demo_keywords_catch": False},
    {"id": "section_232", "vendor": "Mill & Alloy", "should_count": False, "demo_keywords_catch": True},
    {"id": "early_jump", "vendor": "Early Rise Paper", "should_count": False, "demo_keywords_catch": True},
    {"id": "domestic", "vendor": "Homestead Kiln", "should_count": False, "demo_keywords_catch": True},
    {"id": "inflation", "vendor": "Level Pantry", "should_count": False, "demo_keywords_catch": True},
    {"id": "wrong_date", "vendor": "Calendar Imports", "should_count": False, "demo_keywords_catch": True},
    {"id": "later_date", "vendor": "Mekong Tabletop", "should_count": True, "demo_keywords_catch": True},
    {"id": "inferred_origin", "vendor": "Guesswork Goods", "should_count": True, "demo_keywords_catch": True},
    {"id": "peer_control", "vendor": "Clearpour Glass", "should_count": False, "needs_review": False, "demo_keywords_catch": True},
    {"id": "no_control", "vendor": "Orchard Copper", "should_count": False, "needs_review": True, "demo_keywords_catch": True},
]


def write_outputs(gen: Generator):
    for d in (INVOICE_DIR, CONTRACT_DIR):
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.pdf"):
            old.unlink()

    # Invoices and credit memos
    page_counts: dict[str, int] = {}
    scanned_count = 0
    for inv in gen.invoices + gen.credit_memos:
        pdf = render_pdf(inv)
        page_counts[inv.number] = page_count(pdf)
        if inv.scanned:
            pdf = scanify(pdf, gen.rng, gen.np_rng)
            scanned_count += 1
        (INVOICE_DIR / inv.filename).write_bytes(pdf)

    # Contracts
    contracts_meta: dict[str, dict] = {}
    for s in SUPPLIERS.values():
        if not s.contract_file:
            continue
        pdf, meta = render_contract(s)
        (CONTRACT_DIR / s.contract_file).write_bytes(pdf)
        meta["document_url"] = f"data/contracts/{s.contract_file}"
        contracts_meta[s.key] = meta

    # labels.csv
    with (DATA_DIR / "labels.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["invoice_number", "line_index", "description", "category", "amount"])
        for inv in gen.invoices + gen.credit_memos:
            for idx, l in enumerate(inv.all_lines()):
                w.writerow([inv.number, idx, l.description, l.category, f"{l.amount:.2f}"])

    # bills.json
    bills = []
    for inv in gen.invoices:
        bills.append(
            {
                "id": inv.id,
                "vendor": {"id": inv.supplier.id, "name": inv.supplier.name},
                "invoice_number": inv.number,
                "issued_at": inv.issued.isoformat(),
                "due_at": inv.due.isoformat(),
                "paid_at": (inv.due - timedelta(days=gen.rng.randint(0, 5))).isoformat(),
                "amount": f2(inv.total),
                "currency": "USD",
                "status": "PAID",
                "line_items": [
                    {
                        "line_index": idx,
                        "sku": l.sku,
                        "description": l.description,
                        "quantity": float(l.qty),
                        "unit_price": f2(l.unit_price),
                        "amount": f2(l.amount),
                        "country_of_origin": l.country,
                        "hts_chapter": l.hts,
                    }
                    for idx, l in enumerate(inv.all_lines())
                ],
                "document_url": f"data/invoices/{inv.filename}",
                "document_is_scanned_image": inv.scanned,
                "page_count": page_counts[inv.number],
            }
        )
    (DATA_DIR / "bills.json").write_text(json.dumps(bills, indent=2) + "\n")

    # vendors.json
    vendors = []
    for s in SUPPLIERS.values():
        invs = [i for i in gen.invoices if i.supplier is s]
        vendors.append(
            {
                "id": s.id,
                "name": s.name,
                "contact_email": s.email,
                "phone": s.phone,
                "address": {"line1": s.address[0], "line2": s.address[1], "country": "US"},
                "payment_terms": f"NET_{s.terms_days}",
                "primary_country_of_origin": s.country_of_origin,
                "bill_count": len(invs),
                "total_paid": f2(sum((i.total for i in invs), Decimal("0"))),
                "first_bill_at": min(i.issued for i in invs).isoformat(),
                "last_bill_at": max(i.issued for i in invs).isoformat(),
                "contract": contracts_meta.get(s.key),
            }
        )
    (DATA_DIR / "vendors.json").write_text(json.dumps(vendors, indent=2) + "\n")

    # vendor_credits.json
    credits = []
    for m in gen.credit_memos:
        credits.append(
            {
                "id": m.id,
                "vendor": {"id": m.supplier.id, "name": m.supplier.name},
                "credit_memo_number": m.number,
                "issued_at": m.issued.isoformat(),
                "amount": f2(-m.total),
                "currency": "USD",
                "status": "AVAILABLE",
                "applied_to_bill_id": None,
                "memo": m.memo,
                "reference": m.reference,
                "document_url": f"data/invoices/{m.filename}",
            }
        )
    (DATA_DIR / "vendor_credits.json").write_text(json.dumps(credits, indent=2) + "\n")

    # ground_truth.json
    gt = build_ground_truth(gen, contracts_meta)
    (DATA_DIR / "ground_truth.json").write_text(json.dumps(gt, indent=2) + "\n")

    return gt, page_counts, scanned_count, len(contracts_meta)


def main():
    gen = Generator(SEED)
    gen.run()
    gt, page_counts, scanned_count, contract_count = write_outputs(gen)

    multi_page = [n for n, c in page_counts.items() if c > 1]
    print("Ramp Recoveries sample data")
    print(f"  seed: {SEED}")
    print(f"  invoices: {len(gen.invoices)}  credit memos: {len(gen.credit_memos)}  contracts: {contract_count}")
    print(f"  scanned (image-only) PDFs: {scanned_count}  multi-page: {', '.join(multi_page) or 'none'}")
    print(f"  tariff window: {gt['tariff_window']['start']} to {gt['tariff_window']['end']}")
    print()
    print(f"  {'Supplier':34} {'Bills':>5} {'Expected':>12} {'Raw price':>12} {'Conserv.':>12} {'Credits':>9} {'Net claim':>12}  Basis")
    for name, v in gt["suppliers"].items():
        print(
            f"  {name:34} {v['invoice_count']:>5} {v['refundable_claim_total']:>12,.2f} {v['raw_price_increase']:>12,.2f} "
            f"{v['conservative_claim']:>12,.2f} {v['credits_already_received']:>9,.2f} {v['net_claim_total']:>12,.2f}  {v['basis']}"
        )
    print()
    t = gt["totals"]
    print(f"  full answer:                   ${t['refundable_claim_total']:,.2f}")
    print(f"  demo keywords should recover:  ${t['demo_refundable_claim_total']:,.2f}")
    print(f"  price claim (expected):        ${t['conservative_claim']:,.2f}")
    print(f"  raw price increase:            ${t['raw_price_increase']:,.2f}")
    print(f"  net after credits (full):      ${t['net_claim_total_after_credits']:,.2f}")
    print(f"  net after credits (demo):      ${t['demo_net_claim_total_after_credits']:,.2f}")
    print(f"  non-refundable (232/301):  ${t['non_refundable_total']:,.2f}")
    print(f"  importer-of-record duty:   ${t['importer_of_record_duty_total']:,.2f} across {len(gt['importer_of_record_cases'])} entries (CBP, not supplier)")
    print()
    print(f"  wrote {DATA_DIR.relative_to(ROOT)}/{{invoices,contracts}}/*.pdf, labels.csv, ground_truth.json, bills.json, vendors.json, vendor_credits.json")


if __name__ == "__main__":
    main()
