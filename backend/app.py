"""Ramp Recoveries API.

The pipeline labels lines and drafts letters. This module stores the result,
walks the claim from Found to Credited, and serves the Bill Pay records a
credit lands on. Dollar math stays in the pipeline.
"""

import json
import os
import threading
import time
import traceback
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import event
from sqlmodel import Field, Session, SQLModel, select

from pipeline.config import BACKEND_DIR, REPO_ROOT, WINDOW_END, WINDOW_START, get_settings
from pipeline.ingest import check_math
from pipeline.models import Bill as PBill
from pipeline.models import Decision, LineItem, Vendor as PVendor, VendorCredit as PVendorCredit, VendorRef, money
from pipeline.run import run_pipeline
from pipeline.saved import load_saved_output, replay_saved
from pipeline.sources import UploadSource

LA = ZoneInfo("America/Los_Angeles")
STEPS = [
    "reading bills",
    "labeling lines",
    "checking prices",
    "reviewing contracts",
    "building claims",
    "drafting letters",
]
CBP_NOTE = "The refund comes from CBP, not from the supplier."
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4817",
    "http://127.0.0.1:4817",
]

# One open bill per vendor the scan will claim, so an approved credit has a next invoice to land on.
_UPCOMING = [
    (
        "Northwind Packaging Co.",
        "bill_upcoming_northwind",
        "NWP-202604-022",
        date(2026, 4, 10),
        date(2026, 5, 10),
        [
            ("NWP-CUP16", "16oz compostable cold cup", Decimal("40"), Decimal("68.00")),
            ("NWP-LID16", "Flat lid for 16oz cup", Decimal("24"), Decimal("42.50")),
            ("FRT", "Freight", Decimal("1"), Decimal("85.00")),
        ],
    ),
    (
        "Harbor & Pine Coffee Equipment",
        "bill_upcoming_harbor",
        "HPC-202605-012",
        date(2026, 5, 15),
        date(2026, 6, 29),
        [
            ("HP-TAMP", "Espresso tamper, 58mm", Decimal("8"), Decimal("220.00")),
            ("HP-PITCH", "Milk pitcher, 20oz", Decimal("10"), Decimal("145.00")),
            ("HP-SVC", "Group head service kit", Decimal("6"), Decimal("480.00")),
        ],
    ),
    (
        "Altamesa Electronics Supply",
        "bill_upcoming_altamesa",
        "ALT-202604-011",
        date(2026, 4, 12),
        date(2026, 5, 12),
        [
            ("ALT-HUB", "USB-C hub", Decimal("10"), Decimal("86.00")),
            ("ALT-CBL", "Display cable, 2m", Decimal("20"), Decimal("24.00")),
        ],
    ),
    (
        "Kestrel Textiles",
        "bill_upcoming_kestrel",
        "KST-202604-008",
        date(2026, 4, 20),
        date(2026, 5, 20),
        [
            ("KST-NAP", "Cocktail napkin, kraft", Decimal("12"), Decimal("18.00")),
        ],
    ),
]


def _now() -> datetime:
    return datetime.now(LA).replace(tzinfo=None)


def _stamp() -> str:
    return datetime.now(LA).isoformat(timespec="seconds")


def money_f(value: object) -> float:
    return float(cents(value))


def cents(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return money(value)
    if isinstance(value, float):
        return money(Decimal(f"{value:.2f}"))
    return money(Decimal(str(value)))


def _loads(raw: str | None, fallback: object) -> object:
    if not raw:
        return fallback
    return json.loads(raw)


class Vendor(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str = Field(index=True)
    contact_email: str | None = None
    phone: str | None = None
    address_json: str = "{}"
    payment_terms: str | None = None
    primary_country_of_origin: str | None = None
    contract_json: str | None = None
    bill_count: int = 0
    total_paid: float = 0
    first_bill_at: date | None = None
    last_bill_at: date | None = None


class Bill(SQLModel, table=True):
    id: str = Field(primary_key=True)
    vendor_id: str = Field(index=True)
    invoice_number: str = Field(index=True)
    issued_at: date
    due_at: date | None = None
    paid_at: date | None = None
    amount: float
    currency: str = "USD"
    status: str = Field(default="PAID", index=True)
    document_url: str | None = None
    document_is_scanned_image: bool = False
    page_count: int = 1
    needs_review: bool = False
    review_reason: str | None = None
    source: str = "bill_pay"


class BillLine(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    bill_id: str = Field(index=True)
    line_index: int
    sku: str
    description: str
    quantity: float
    unit_price: float
    amount: float
    category: str | None = None
    decision: str | None = None
    reason: str | None = None
    labeled_by: str | None = None


class Claim(SQLModel, table=True):
    id: str = Field(primary_key=True)
    vendor_id: str = Field(index=True, unique=True)
    strength: str | None = None
    status: str = "Found"
    refundable_total: float = 0
    gross_refundable: float = 0
    non_refundable_total: float = 0
    credits_applied: float = 0
    ieepa_surcharge_total: float = 0
    price_excess_total: float = 0
    raw_price_increase: float = 0
    subtitle: str = ""
    bill_count: int = 0
    price_reverted: bool | None = None
    contract_json: str = "{}"
    price_history_json: str = "{}"
    status_history_json: str = "[]"


class Evidence(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    claim_id: str = Field(index=True)
    invoice_number: str
    line_index: int
    evidence_date: date
    description: str
    amount: float
    type: str
    labeled_by: str


class Letter(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    claim_id: str = Field(index=True, unique=True)
    body: str
    original_body: str
    status: str = "draft"
    word_count: int = 0
    model: str = ""


class VendorCredit(SQLModel, table=True):
    id: str = Field(primary_key=True)
    vendor_id: str = Field(index=True)
    credit_memo_number: str
    issued_at: date
    amount: float
    currency: str = "USD"
    status: str = "AVAILABLE"
    memo: str | None = None
    reference: str | None = None
    document_url: str | None = None
    applied_to_bill_id: str | None = Field(default=None, index=True)
    source: str = "seed"


class ScanRun(SQLModel, table=True):
    id: str = Field(primary_key=True)
    status: str = Field(default="running", index=True)
    step: str = "reading bills"
    step_index: int = 1
    cached: bool = False
    error: str | None = None
    needs_review_count: int = 0
    usage_json: str = "{}"
    importer_json: str = "[]"
    created_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None


class LetterUpdate(BaseModel):
    body: str


class ShareUpdate(BaseModel):
    import_cost_share: float


def _engine(url: str):
    engine = create_engine_checked(url)

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _record) -> None:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def create_engine_checked(url: str):
    from sqlmodel import create_engine

    return create_engine(url, connect_args={"check_same_thread": False})


def seed_database(session: Session, data_dir: Path) -> None:
    vendors = json.loads((data_dir / "vendors.json").read_text(), parse_float=Decimal)
    by_name: dict[str, str] = {}
    for raw in vendors:
        session.add(
            Vendor(
                id=raw["id"],
                name=raw["name"],
                contact_email=raw.get("contact_email"),
                phone=raw.get("phone"),
                address_json=json.dumps(raw.get("address") or {}),
                payment_terms=raw.get("payment_terms"),
                primary_country_of_origin=raw.get("primary_country_of_origin"),
                contract_json=json.dumps(raw["contract"]) if raw.get("contract") else None,
                bill_count=int(raw.get("bill_count") or 0),
                total_paid=money_f(raw.get("total_paid") or 0),
                first_bill_at=_date(raw.get("first_bill_at")),
                last_bill_at=_date(raw.get("last_bill_at")),
            )
        )
        by_name[raw["name"]] = raw["id"]

    bills = json.loads((data_dir / "bills.json").read_text(), parse_float=Decimal)
    for raw in bills:
        session.add(
            Bill(
                id=raw["id"],
                vendor_id=raw["vendor"]["id"],
                invoice_number=raw["invoice_number"],
                issued_at=_date(raw["issued_at"]),
                due_at=_date(raw.get("due_at")),
                paid_at=_date(raw.get("paid_at")),
                amount=money_f(raw["amount"]),
                currency=raw.get("currency") or "USD",
                status=raw.get("status") or "PAID",
                document_url=raw.get("document_url"),
                document_is_scanned_image=bool(raw.get("document_is_scanned_image")),
                page_count=int(raw.get("page_count") or 1),
                source="bill_pay",
            )
        )
        for line in raw.get("line_items") or []:
            session.add(_line(raw["id"], line))

    for raw in json.loads((data_dir / "vendor_credits.json").read_text(), parse_float=Decimal):
        session.add(
            VendorCredit(
                id=raw["id"],
                vendor_id=raw["vendor"]["id"],
                credit_memo_number=raw["credit_memo_number"],
                issued_at=_date(raw["issued_at"]),
                amount=money_f(raw["amount"]),
                currency=raw.get("currency") or "USD",
                status=raw.get("status") or "AVAILABLE",
                memo=raw.get("memo"),
                reference=raw.get("reference"),
                document_url=raw.get("document_url"),
                applied_to_bill_id=raw.get("applied_to_bill_id"),
                source="seed",
            )
        )

    for name, bill_id, number, issued, due, lines in _UPCOMING:
        vendor_id = by_name[name]
        product = sum((qty * unit for sku, _desc, qty, unit in lines if sku != "FRT"), Decimal("0"))
        freight = sum((qty * unit for sku, _desc, qty, unit in lines if sku == "FRT"), Decimal("0"))
        tax = money(product * Decimal("0.1025"))
        total = money(product + freight + tax)
        session.add(
            Bill(
                id=bill_id,
                vendor_id=vendor_id,
                invoice_number=number,
                issued_at=issued,
                due_at=due,
                amount=money_f(total),
                status="UNPAID",
                source="bill_pay",
            )
        )
        drafted = [
            {"line_index": index, "sku": sku, "description": desc, "quantity": qty, "unit_price": unit, "amount": money(qty * unit)}
            for index, (sku, desc, qty, unit) in enumerate(lines)
        ]
        drafted.append(
            {
                "line_index": len(drafted),
                "sku": "TAX",
                "description": "Sales tax (10.25%)",
                "quantity": Decimal("1"),
                "unit_price": tax,
                "amount": tax,
            }
        )
        for line in drafted:
            session.add(_line(bill_id, line))


def _line(bill_id: str, line: dict) -> BillLine:
    return BillLine(
        bill_id=bill_id,
        line_index=int(line["line_index"]),
        sku=line["sku"],
        description=line["description"],
        quantity=float(line["quantity"]),
        unit_price=money_f(line["unit_price"]),
        amount=money_f(line["amount"]),
    )


def _date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def create_app(database_url: str | None = None) -> FastAPI:
    url = database_url or os.environ.get("DATABASE_URL", "sqlite:///./recoveries.db")
    engine = _engine(url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        SQLModel.metadata.create_all(engine)
        settings = get_settings()
        with Session(engine) as session:
            if session.exec(select(Vendor)).first() is None:
                seed_database(session, settings.resolved_data_dir())
                session.commit()
        _seed_saved_scan(engine)
        yield

    app = FastAPI(title="Ramp Recoveries", lifespan=lifespan)
    app.state.engine = engine
    app.state.pipeline_cache = {}
    app.state.cache_lock = threading.Lock()
    app.state.scan_lock = threading.Lock()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_session():
        with Session(engine) as session:
            yield session

    SessionDep = Annotated[Session, Depends(get_session)]

    @app.post("/api/recoveries/scan")
    def start_scan() -> dict:
        return _start_scan(app)

    @app.get("/api/recoveries/scan/{scan_id}")
    def scan_status(scan_id: str, session: SessionDep) -> dict:
        scan = session.get(ScanRun, scan_id)
        if scan is None:
            raise HTTPException(status_code=404, detail="Scan not found.")
        return _scan_payload(scan)

    @app.get("/api/recoveries")
    def recoveries(session: SessionDep) -> dict:
        return _summary(session)

    @app.get("/api/recoveries/{vendor_id}")
    def recovery_detail(vendor_id: str, session: SessionDep) -> dict:
        claim = _claim_for(session, vendor_id)
        vendor = session.get(Vendor, vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail="Vendor not found.")
        return _detail(session, vendor, claim)

    @app.put("/api/recoveries/{vendor_id}/import-cost-share")
    def update_import_share(vendor_id: str, update: ShareUpdate, session: SessionDep) -> dict:
        if not 0.01 <= update.import_cost_share <= 1:
            raise HTTPException(status_code=400, detail="Import cost share has to be between 1% and 100%.")
        claim = _claim_for(session, vendor_id)
        if claim.status in {"Sent", "Credited"}:
            raise HTTPException(status_code=409, detail="This claim was already sent.")
        vendor = session.get(Vendor, vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail="Vendor not found.")
        history = _loads(claim.price_history_json, {})
        if not history.get("math"):
            raise HTTPException(status_code=400, detail="This claim has no price assumption to edit.")
        from pipeline.prices import recalculate_share

        share = Decimal(str(update.import_cost_share))
        contract = _loads(claim.contract_json, {})
        result = recalculate_share(
            history,
            share,
            ieepa=cents(claim.ieepa_surcharge_total),
            credits=cents(claim.credits_applied),
            non_refundable=cents(claim.non_refundable_total),
            clause=bool(contract.get("refund_or_credit_clause")),
        )
        claim.price_history_json = json.dumps(result["history"])
        claim.price_excess_total = money_f(result["price_excess"])
        claim.raw_price_increase = money_f(result["raw"])
        claim.gross_refundable = money_f(result["gross"])
        claim.refundable_total = money_f(result["refundable"])
        claim.price_reverted = result["reverted"]
        claim.strength = result["strength"].value if result["strength"] else None
        _replace_price_evidence(session, claim.id, result["lines"])
        session.flush()
        letter = session.exec(select(Letter).where(Letter.claim_id == claim.id)).first()
        if letter is not None and letter.body == letter.original_body and letter.status != "sent":
            rebuilt = _letter_from_claim(session, vendor, claim, contract)
            letter.body = rebuilt
            letter.original_body = rebuilt
            letter.word_count = _word_count(rebuilt)
            session.add(letter)
        session.add(claim)
        session.commit()
        session.refresh(claim)
        return _detail(session, vendor, claim)

    @app.put("/api/recoveries/{vendor_id}/letter")
    def save_letter(vendor_id: str, update: LetterUpdate, session: SessionDep) -> dict:
        claim = _claim_for(session, vendor_id)
        letter = session.exec(select(Letter).where(Letter.claim_id == claim.id)).first()
        if letter is None:
            raise HTTPException(status_code=404, detail="This claim has no letter to edit.")
        if not update.body.strip():
            raise HTTPException(status_code=400, detail="Letter body is empty.")
        letter.body = update.body
        letter.word_count = _word_count(letter.body)
        session.add(letter)
        session.commit()
        session.refresh(letter)
        return _letter_payload(letter)

    @app.post("/api/recoveries/{vendor_id}/approve")
    def approve(vendor_id: str, session: SessionDep) -> dict:
        claim = _claim_for(session, vendor_id)
        letter = session.exec(select(Letter).where(Letter.claim_id == claim.id)).first()
        if letter is None:
            raise HTTPException(status_code=409, detail="Draft a letter before sending.")
        if claim.status != "Drafted":
            raise HTTPException(status_code=409, detail=f"A {claim.status} claim cannot be sent.")
        letter.status = "sent"
        claim.status = "Sent"
        _push_status(claim, "Sent")
        session.add(letter)
        session.add(claim)
        session.commit()
        return {"vendor_id": vendor_id, "status": claim.status, "letter_status": letter.status}

    @app.post("/api/recoveries/{vendor_id}/simulate-agree")
    def simulate_agree(vendor_id: str, session: SessionDep) -> dict:
        if not get_settings().use_demo:
            raise HTTPException(
                status_code=403,
                detail="Record the supplier's reply before applying a credit.",
            )
        claim = _claim_for(session, vendor_id)
        if claim.status == "Credited":
            raise HTTPException(status_code=409, detail="This claim is already credited.")
        if claim.status != "Sent":
            raise HTTPException(status_code=409, detail="Approve the letter before the supplier agrees.")
        if claim.refundable_total <= 0:
            raise HTTPException(status_code=400, detail="There is nothing to credit.")
        existing = session.exec(
            select(VendorCredit).where(VendorCredit.vendor_id == vendor_id, VendorCredit.source == "recovery")
        ).first()
        if existing is not None:
            raise HTTPException(status_code=409, detail="A recovery credit already exists for this vendor.")
        bill = _next_unpaid(session, vendor_id)
        credit = VendorCredit(
            id=f"vc_recovery_{vendor_id}",
            vendor_id=vendor_id,
            credit_memo_number=f"RCV-{vendor_id[-6:].upper()}",
            issued_at=datetime.now(LA).date(),
            amount=money_f(claim.refundable_total),
            status="APPLIED" if bill else "AVAILABLE",
            memo="Supplier agreed to the tariff refund. Applied to the next bill.",
            reference=claim.subtitle or "IEEPA tariff recovery",
            applied_to_bill_id=bill.id if bill else None,
            source="recovery",
        )
        claim.status = "Credited"
        _push_status(claim, "Credited")
        session.add(credit)
        session.add(claim)
        session.commit()
        return {
            "vendor_id": vendor_id,
            "status": claim.status,
            "credit_id": credit.id,
            "amount": credit.amount,
            "applied_to_bill_id": credit.applied_to_bill_id,
        }

    @app.get("/api/importer-cases")
    def importer_cases(session: SessionDep) -> dict:
        cases = _importer_cases(session)
        total = money_f(sum((Decimal(str(case["amount"])) for case in cases), Decimal("0")))
        return {"count": len(cases), "total": total, "note": CBP_NOTE, "cases": cases}

    @app.get("/api/bills")
    def list_bills(session: SessionDep, status: str | None = None) -> list[dict]:
        query = select(Bill)
        if status:
            query = query.where(Bill.status == status.upper())
        bills = session.exec(query).all()
        vendors = {vendor.id: vendor for vendor in session.exec(select(Vendor)).all()}
        rows = [_bill_summary(session, bill, vendors.get(bill.vendor_id)) for bill in bills]
        rows.sort(key=lambda row: (row["status"] != "UNPAID", row["due_at"] or row["issued_at"] or ""))
        return rows

    @app.get("/api/bills/{bill_id}")
    def bill_detail(bill_id: str, session: SessionDep) -> dict:
        bill = session.get(Bill, bill_id)
        if bill is None:
            raise HTTPException(status_code=404, detail="Bill not found.")
        vendor = session.get(Vendor, bill.vendor_id)
        lines = session.exec(select(BillLine).where(BillLine.bill_id == bill.id).order_by(BillLine.line_index)).all()
        applied = _applied_credits(session, bill.id)
        summary = _bill_summary(session, bill, vendor)
        summary["line_items"] = [
            {
                "line_index": line.line_index,
                "sku": line.sku,
                "description": line.description,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "amount": line.amount,
                "category": line.category,
                "decision": line.decision,
                "reason": line.reason,
                "labeled_by": line.labeled_by,
            }
            for line in lines
        ]
        summary["applied_credits"] = applied
        summary["applied_credit"] = applied[0] if applied else None
        summary["document_url"] = f"/api/bills/{bill.id}/document" if bill.document_url else None
        summary["needs_review"] = bill.needs_review
        summary["review_reason"] = bill.review_reason
        return summary

    @app.get("/api/bills/{bill_id}/document")
    def bill_document(bill_id: str, session: SessionDep) -> FileResponse:
        bill = session.get(Bill, bill_id)
        if bill is None:
            raise HTTPException(status_code=404, detail="Bill not found.")
        return _pdf(bill.document_url)

    @app.get("/api/vendors")
    def list_vendors(session: SessionDep) -> list[dict]:
        claims = {claim.vendor_id: claim for claim in session.exec(select(Claim)).all()}
        return [_vendor_card(vendor, claims.get(vendor.id)) for vendor in session.exec(select(Vendor).order_by(Vendor.name)).all()]

    @app.get("/api/vendors/{vendor_id}")
    def vendor_profile(vendor_id: str, session: SessionDep) -> dict:
        vendor = session.get(Vendor, vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail="Vendor not found.")
        claim = session.exec(select(Claim).where(Claim.vendor_id == vendor_id)).first()
        bills = session.exec(select(Bill).where(Bill.vendor_id == vendor_id)).all()
        credits = session.exec(select(VendorCredit).where(VendorCredit.vendor_id == vendor_id)).all()
        card = _vendor_card(vendor, claim)
        card["phone"] = vendor.phone
        card["address"] = _loads(vendor.address_json, {})
        card["payment_terms"] = vendor.payment_terms
        card["primary_country_of_origin"] = vendor.primary_country_of_origin
        card["contract"] = _contract_row(vendor, claim)
        card["bills"] = [_bill_summary(session, bill, vendor) for bill in sorted(bills, key=lambda item: item.issued_at, reverse=True)]
        card["credits"] = [_credit_payload(credit) for credit in credits]
        card["recovery"] = _claim_card(session, claim) if claim else None
        return card

    @app.get("/api/contracts")
    def contracts(session: SessionDep) -> list[dict]:
        rows = []
        claims = {claim.vendor_id: claim for claim in session.exec(select(Claim)).all()}
        for vendor in session.exec(select(Vendor).order_by(Vendor.name)).all():
            row = _contract_row(vendor, claims.get(vendor.id))
            if row is not None:
                rows.append(row)
        return rows

    @app.get("/api/contracts/{vendor_id}/document")
    def contract_document(vendor_id: str, session: SessionDep) -> FileResponse:
        vendor = session.get(Vendor, vendor_id)
        if vendor is None or not vendor.contract_json:
            raise HTTPException(status_code=404, detail="Contract not found.")
        contract = json.loads(vendor.contract_json)
        return _pdf(contract.get("document_url"))

    @app.post("/api/uploads")
    async def uploads(files: list[UploadFile] = File(...)) -> dict:
        if not files:
            raise HTTPException(status_code=400, detail="Attach at least one PDF.")
        dest = BACKEND_DIR / "uploads"
        dest.mkdir(exist_ok=True)
        saved: list[Path] = []
        for upload in files:
            name = Path(upload.filename or "").name
            if not name.lower().endswith(".pdf"):
                raise HTTPException(status_code=400, detail="Upload PDF bills only.")
            target = dest / name
            target.write_bytes(await upload.read())
            saved.append(target)
        created, skipped = _ingest_uploads(engine, saved)
        scan = _start_scan(app)
        return {"scan_id": scan["scan_id"], "status": scan["status"], "created": created, "skipped": skipped}

    @app.get("/api/home")
    def home(session: SessionDep) -> dict:
        return _home(session)

    @app.post("/api/demo/reset")
    def reset() -> dict:
        with Session(engine) as session:
            cleared = _reset(session)
            session.commit()
        app.state.pipeline_cache.clear()
        return {"ok": True, "cleared": cleared}

    return app


def _start_scan(app: FastAPI) -> dict:
    with app.state.scan_lock:
        with Session(app.state.engine) as session:
            running = session.exec(select(ScanRun).where(ScanRun.status == "running")).first()
            if running is not None:
                return {"scan_id": running.id, "status": running.status}
            scan = ScanRun(id=uuid4().hex, status="running", step=STEPS[0], step_index=1)
            session.add(scan)
            session.commit()
            scan_id = scan.id
        threading.Thread(target=_execute_scan, args=(app, scan_id), daemon=True).start()
        return {"scan_id": scan_id, "status": "running"}


def _scan_source(settings) -> str:
    if settings.anthropic_api_key.strip() and not settings.demo_mode:
        return "live"
    if replay_saved(settings):
        return "saved"
    return "rules"


def _seed_saved_scan(engine) -> None:
    """Open on the saved model run when there is no key and the database is empty of claims."""
    if not replay_saved(get_settings()):
        return
    with Session(engine) as session:
        if session.exec(select(Claim)).first() is not None:
            return
        bills, _vendors, _credits, _key = _pipeline_inputs(session)
        output = load_saved_output()
        review_count = _persist(session, output, bills)
        scan = ScanRun(
            id=uuid4().hex,
            status="complete",
            step=STEPS[-1],
            step_index=len(STEPS),
            needs_review_count=review_count,
            usage_json=output.usage.model_dump_json(),
            importer_json=json.dumps(_importer_payload(session, output.importer_cases)),
            finished_at=_now(),
        )
        session.add(scan)
        session.commit()


def _execute_scan(app: FastAPI, scan_id: str) -> None:
    delay = float(os.environ.get("RECOVERIES_STEP_DELAY", "0.35"))
    try:
        _set_step(app, scan_id, 0)
        with Session(app.state.engine) as session:
            bills, vendors, credits, key = _pipeline_inputs(session)
        settings = get_settings()
        source = _scan_source(settings)
        cache_key = (source, key)
        with app.state.cache_lock:
            cached = cache_key in app.state.pipeline_cache
            if not cached:
                if source == "saved":
                    produced = load_saved_output()
                else:
                    produced = run_pipeline(settings, bills, vendors, credits, settings.resolved_data_dir())
                app.state.pipeline_cache[cache_key] = produced
            output = app.state.pipeline_cache[cache_key]
        _mark_cached(app, scan_id, cached)
        for index in range(len(STEPS)):
            _set_step(app, scan_id, index)
            if delay > 0:
                time.sleep(delay)
        with Session(app.state.engine) as session:
            review_count = _persist(session, output, bills)
            scan = session.get(ScanRun, scan_id)
            scan.status = "complete"
            scan.step = STEPS[-1]
            scan.step_index = len(STEPS)
            scan.cached = cached
            scan.needs_review_count = review_count
            scan.usage_json = output.usage.model_dump_json()
            scan.importer_json = json.dumps(_importer_payload(session, output.importer_cases))
            scan.finished_at = _now()
            session.add(scan)
            session.commit()
    except Exception as exc:
        trace = traceback.format_exc(limit=8)
        with Session(app.state.engine) as session:
            scan = session.get(ScanRun, scan_id)
            if scan is not None:
                scan.status = "error"
                scan.error = f"{exc.__class__.__name__}: {exc}\n{trace}"[-2000:]
                scan.finished_at = _now()
                session.add(scan)
                session.commit()


def _set_step(app: FastAPI, scan_id: str, index: int) -> None:
    with Session(app.state.engine) as session:
        scan = session.get(ScanRun, scan_id)
        if scan is None or scan.status != "running":
            return
        scan.step = STEPS[index]
        scan.step_index = index + 1
        session.add(scan)
        session.commit()


def _mark_cached(app: FastAPI, scan_id: str, cached: bool) -> None:
    with Session(app.state.engine) as session:
        scan = session.get(ScanRun, scan_id)
        if scan is None:
            return
        scan.cached = cached
        session.add(scan)
        session.commit()


def _line_facts() -> dict[tuple[str, int], tuple[str | None, str | None]]:
    """Country and HTS from the sample file. The bill table has no columns for them."""
    path = get_settings().resolved_data_dir() / "bills.json"
    facts: dict[tuple[str, int], tuple[str | None, str | None]] = {}
    if not path.exists():
        return facts
    for bill in json.loads(path.read_text()):
        for line in bill.get("line_items") or []:
            facts[(bill["invoice_number"], int(line["line_index"]))] = (
                line.get("country_of_origin"),
                line.get("hts_chapter"),
            )
    return facts


def _pipeline_inputs(session: Session) -> tuple[list[PBill], list[PVendor], list[PVendorCredit], tuple]:
    vendors = {vendor.id: vendor for vendor in session.exec(select(Vendor)).all()}
    facts = _line_facts()
    pbills: list[PBill] = []
    key: list[tuple] = []
    for bill in session.exec(select(Bill).where(Bill.status != "UNPAID")).all():
        lines = session.exec(select(BillLine).where(BillLine.bill_id == bill.id).order_by(BillLine.line_index)).all()
        if bill.status == "UPLOADED" and not lines:
            continue
        vendor = vendors[bill.vendor_id]
        pbills.append(check_math(_to_pbill(bill, lines, vendor, facts)))
        key.append((bill.id, bill.invoice_number, money_f(bill.amount), len(lines)))
    pvendors = [_to_pvendor(vendor) for vendor in vendors.values()]
    credits = [
        _to_pcredit(credit, vendors[credit.vendor_id])
        for credit in session.exec(select(VendorCredit)).all()
        if credit.source != "recovery" and credit.vendor_id in vendors
    ]
    pbills.sort(key=lambda bill: (bill.issued_at, bill.invoice_number))
    return pbills, pvendors, credits, tuple(sorted(key))


def _to_pbill(
    bill: Bill,
    lines: list[BillLine],
    vendor: Vendor,
    facts: dict[tuple[str, int], tuple[str | None, str | None]] | None = None,
) -> PBill:
    return PBill(
        id=bill.id,
        vendor=VendorRef(id=vendor.id, name=vendor.name),
        invoice_number=bill.invoice_number,
        issued_at=bill.issued_at,
        due_at=bill.due_at,
        paid_at=bill.paid_at,
        amount=cents(bill.amount),
        currency=bill.currency,
        status=bill.status,
        line_items=[
            LineItem(
                line_index=line.line_index,
                sku=line.sku,
                description=line.description,
                quantity=cents(line.quantity) if line.sku == "TAX" else Decimal(str(line.quantity)),
                unit_price=cents(line.unit_price),
                amount=cents(line.amount),
                country_of_origin=(facts or {}).get((bill.invoice_number, line.line_index), (None, None))[0],
                hts_chapter=(facts or {}).get((bill.invoice_number, line.line_index), (None, None))[1],
            )
            for line in lines
        ],
        document_url=bill.document_url,
        document_is_scanned_image=bill.document_is_scanned_image,
        page_count=bill.page_count,
        needs_review=bill.needs_review,
        review_reason=bill.review_reason,
        source=bill.source,
    )


def _to_pvendor(vendor: Vendor) -> PVendor:
    address = _loads(vendor.address_json, {})
    return PVendor(
        id=vendor.id,
        name=vendor.name,
        contact_email=vendor.contact_email,
        phone=vendor.phone,
        address=address or None,
        payment_terms=vendor.payment_terms,
        primary_country_of_origin=vendor.primary_country_of_origin,
    )


def _to_pcredit(credit: VendorCredit, vendor: Vendor) -> PVendorCredit:
    return PVendorCredit(
        id=credit.id,
        vendor=VendorRef(id=vendor.id, name=vendor.name),
        credit_memo_number=credit.credit_memo_number,
        issued_at=credit.issued_at,
        amount=cents(credit.amount),
        currency=credit.currency,
        status=credit.status,
        memo=credit.memo,
        reference=credit.reference,
        document_url=credit.document_url,
    )


def _persist(session: Session, output, bills: list[PBill]) -> int:
    _write_labels(session, output.labels)
    letters = {letter.vendor_name: letter for letter in output.letters}
    contracts = output.contracts
    kept: set[str] = set()
    for claim in output.claims:
        if claim.strength is None and not claim.needs_review:
            continue
        history = _price_history(claim, bills, output.prices)
        contract = contracts.get(claim.vendor_name)
        row = session.get(Claim, f"clm_{claim.vendor_id}")
        fresh = row is None
        if fresh:
            row = Claim(id=f"clm_{claim.vendor_id}", vendor_id=claim.vendor_id)
        locked = row.status in {"Sent", "Credited"}
        row.strength = claim.strength.value if claim.strength else None
        row.refundable_total = money_f(claim.refundable_total)
        row.gross_refundable = money_f(claim.gross_refundable)
        row.non_refundable_total = money_f(claim.non_refundable_total)
        row.credits_applied = money_f(claim.credits_applied)
        row.ieepa_surcharge_total = money_f(claim.ieepa_surcharge_total)
        row.price_excess_total = money_f(claim.price_excess_total)
        row.raw_price_increase = history["raw_price_increase"]
        row.subtitle = _subtitle(claim)
        row.bill_count = len({item.invoice_number for item in claim.evidence if item.type != "vendor_credit" and item.amount > 0})
        if row.bill_count == 0:
            during = {
                point["invoice_number"]
                for sku in history.get("skus", [])
                for point in sku.get("points", [])
                if point.get("period") == "during"
            }
            row.bill_count = len(during)
        row.price_reverted = claim.price_jump_reverted
        row.contract_json = json.dumps(_contract_finding(claim, contract))
        row.price_history_json = json.dumps(history)
        if not locked:
            if claim.needs_review and claim.strength is None:
                row.status = "Needs review"
                history_rows = [{"status": "Needs review", "at": _stamp()}]
            else:
                drafted = letters.get(claim.vendor_name) is not None
                row.status = "Drafted" if drafted else "Found"
                stamp = _stamp()
                history_rows = [{"status": "Found", "at": stamp}]
                if drafted:
                    history_rows.append({"status": "Drafted", "at": stamp})
            row.status_history_json = json.dumps(history_rows)
        session.add(row)
        session.flush()
        _replace_evidence(session, row.id, claim.evidence)
        _upsert_letter(session, row, letters.get(claim.vendor_name), locked)
        kept.add(row.vendor_id)

    for old in session.exec(select(Claim)).all():
        if old.vendor_id in kept or old.status in {"Sent", "Credited"}:
            continue
        _delete_claim(session, old)
    review = sum(1 for label in output.labels if label.decision is Decision.needs_review)
    review += sum(1 for bill in session.exec(select(Bill)).all() if bill.needs_review)
    review += sum(1 for sku in output.prices.skus if sku.needs_review)
    return review


def _write_labels(session: Session, labels) -> None:
    by_invoice: dict[str, dict[int, object]] = {}
    for label in labels:
        by_invoice.setdefault(label.invoice_number, {})[label.line_index] = label
    bills = {bill.invoice_number: bill for bill in session.exec(select(Bill)).all()}
    for invoice, labeled in by_invoice.items():
        bill = bills.get(invoice)
        if bill is None:
            continue
        for line in session.exec(select(BillLine).where(BillLine.bill_id == bill.id)).all():
            label = labeled.get(line.line_index)
            if label is None:
                continue
            line.category = label.category.value
            line.decision = label.decision.value
            line.reason = label.reason
            line.labeled_by = label.labeled_by
            session.add(line)


def _replace_evidence(session: Session, claim_id: str, items) -> None:
    for old in session.exec(select(Evidence).where(Evidence.claim_id == claim_id)).all():
        session.delete(old)
    session.flush()
    for item in items:
        session.add(
            Evidence(
                claim_id=claim_id,
                invoice_number=item.invoice_number,
                line_index=item.line_index,
                evidence_date=item.date,
                description=item.description,
                amount=money_f(item.amount),
                type=item.type,
                labeled_by=item.labeled_by,
            )
        )


def _upsert_letter(session: Session, claim: Claim, drafted, locked: bool) -> None:
    existing = session.exec(select(Letter).where(Letter.claim_id == claim.id)).first()
    if drafted is None:
        if existing is not None and not locked and existing.status != "sent":
            session.delete(existing)
        return
    edited = existing is not None and existing.body != existing.original_body
    if existing is not None and (edited or existing.status == "sent" or locked):
        return
    if existing is None:
        existing = Letter(claim_id=claim.id, body=drafted.body, original_body=drafted.body)
    existing.body = drafted.body
    existing.original_body = drafted.body
    existing.status = "draft"
    existing.word_count = drafted.word_count
    existing.model = drafted.model
    session.add(existing)


def _delete_claim(session: Session, claim: Claim) -> None:
    for letter in session.exec(select(Letter).where(Letter.claim_id == claim.id)).all():
        session.delete(letter)
    for item in session.exec(select(Evidence).where(Evidence.claim_id == claim.id)).all():
        session.delete(item)
    session.delete(claim)


def _subtitle(claim) -> str:
    surcharges: list[str] = []
    for item in claim.evidence:
        if item.type == "tariff_ieepa_surcharge" and item.description not in surcharges:
            surcharges.append(item.description)
    if surcharges:
        return " · ".join(surcharges[:2])
    if any(item.type == "price_excess" for item in claim.evidence):
        return "Price increase"
    for item in claim.evidence:
        if item.type == "tariff_other":
            return item.description
    if claim.needs_review:
        return "Needs review"
    return ""


def _price_history(claim, bills: list[PBill], prices) -> dict:
    findings = [finding for finding in prices.findings if finding.vendor_name == claim.vendor_name]
    by_sku: dict[str, list] = {}
    for finding in findings:
        by_sku.setdefault(finding.sku, []).append(finding)
    shown = [sku for sku in prices.skus if sku.vendor_name == claim.vendor_name and _show_sku(sku)]
    skus = []
    math_rows = []
    raw_total = Decimal("0")
    conservative_total = Decimal("0")
    share = None
    for summary in sorted(shown, key=lambda sku: sku.sku):
        flags = by_sku.get(summary.sku, [])
        flagged = {(finding.invoice_number, finding.line_index): finding for finding in flags}
        points = []
        lines = []
        raw = Decimal("0")
        description = flags[-1].description if flags else summary.sku
        for bill in bills:
            if bill.vendor.name != claim.vendor_name:
                continue
            for line in bill.line_items:
                if line.sku != summary.sku:
                    continue
                description = line.description
                if bill.issued_at < WINDOW_START:
                    period = "before"
                elif bill.issued_at > WINDOW_END:
                    period = "after"
                else:
                    period = "during"
                finding = flagged.get((bill.invoice_number, line.line_index))
                points.append(
                    {
                        "period": period,
                        "date": bill.issued_at.isoformat(),
                        "unit_price": money_f(line.unit_price),
                        "invoice_number": bill.invoice_number,
                        "expected_price": money_f(finding.expected) if finding else None,
                    }
                )
                if finding is not None and summary.baseline is not None:
                    raw += (line.unit_price - summary.baseline) * line.quantity
                if _claim_line(summary, bill.issued_at, line.unit_price):
                    lines.append(
                        {
                            "quantity": format(line.quantity, "f"),
                            "unit_price": f"{money(line.unit_price):.2f}",
                            "invoice_number": bill.invoice_number,
                            "line_index": line.line_index,
                            "date": bill.issued_at.isoformat(),
                            "description": line.description,
                            "labeled_by": summary.labeled_by,
                        }
                    )
        raw = money(raw)
        conservative = money(sum((finding.amount for finding in flags), Decimal("0")))
        raw_total += raw
        conservative_total += conservative
        points.sort(key=lambda point: (point["date"], point["invoice_number"]))
        reference = _reference_price(summary, flags)
        if share is None:
            share = summary.import_cost_share
        skus.append(
            {
                "sku": summary.sku,
                "description": description,
                "baseline": money_f(summary.baseline) if summary.baseline is not None else 0,
                "expected_price": money_f(reference),
                "benchmark_price": money_f(summary.benchmark_price) if summary.benchmark_price is not None else None,
                "benchmark_is_mock": True,
                "benchmark_source": "ramp_network_benchmark",
                "fell_back": summary.fell_back_after_window,
                "raw_increase": money_f(raw),
                "conservative_increase": money_f(conservative),
                "points": points,
                "tests": [test.model_dump() for test in summary.tests],
                "country": summary.country,
                "hts_chapter": summary.hts_chapter,
                "origin_inferred": summary.origin_inferred,
                "tariff_rate": money_f(summary.tariff_rate) if summary.tariff_rate is not None else None,
                "claim_low": money_f(summary.claim_low),
                "claim_expected": money_f(summary.claim_expected),
                "claim_high": money_f(summary.claim_high),
            }
        )
        math_rows.append(
            {
                "sku": summary.sku,
                "description": description,
                "baseline": f"{summary.baseline:.2f}" if summary.baseline is not None else None,
                "tariff_rate": format(summary.tariff_rate, "f") if summary.tariff_rate is not None else None,
                "max_unit_jump": format(summary.max_unit_jump, "f"),
                "control_percent": format(summary.control_percent, "f") if summary.control_percent is not None else None,
                "origin_inferred": summary.origin_inferred,
                "fell_back": summary.fell_back_after_window,
                "tests": [test.model_dump() for test in summary.tests],
                "lines": lines,
            }
        )
    return {
        "skus": skus,
        "math": math_rows,
        "import_cost_share": money_f(share) if share is not None else 0.6,
        "raw_price_increase": money_f(raw_total),
        "conservative_price_increase": money_f(conservative_total),
        "evidence_tier": claim.evidence_tier,
        "tier_reasons": claim.tier_reasons,
        "claim_low": money_f(claim.claim_low) if claim.claim_low is not None else None,
        "claim_expected": money_f(claim.claim_expected) if claim.claim_expected is not None else None,
        "claim_high": money_f(claim.claim_high) if claim.claim_high is not None else None,
        "origin_inferred_only": claim.origin_inferred_only,
    }


def _show_sku(summary) -> bool:
    if summary.qualified or summary.needs_review:
        return True
    size = next((test for test in summary.tests if test.id == "size"), None)
    others = [test for test in summary.tests if test.required and test.id != "size"]
    return bool(size and size.status != "pass" and others and all(test.status == "pass" for test in others))


def _claim_line(summary, issued, unit_price) -> bool:
    if summary.baseline is None or summary.jump_on is None:
        return False
    return WINDOW_START <= issued <= WINDOW_END and issued >= summary.jump_on and unit_price > summary.baseline


def _reference_price(summary, flags):
    if flags:
        return flags[-1].expected
    if summary.baseline is None:
        return Decimal("0")
    if summary.control_percent is not None:
        return summary.baseline * (1 + summary.control_percent)
    return summary.baseline


def _replace_price_evidence(session: Session, claim_id: str, lines: list[dict]) -> None:
    for old in session.exec(select(Evidence).where(Evidence.claim_id == claim_id, Evidence.type == "price_excess")).all():
        session.delete(old)
    session.flush()
    for line in lines:
        session.add(
            Evidence(
                claim_id=claim_id,
                invoice_number=line["invoice_number"],
                line_index=int(line["line_index"]),
                evidence_date=date.fromisoformat(line["date"]),
                description=line["description"],
                amount=money_f(line["amount"]),
                type="price_excess",
                labeled_by=line.get("labeled_by") or "price",
            )
        )


def _letter_from_claim(session: Session, vendor: Vendor, claim: Claim, contract: dict) -> str:
    from pipeline.config import BUYER_NAME, SIGN_OFF
    from pipeline.letters import _template
    from pipeline.models import LetterFacts

    items = session.exec(select(Evidence).where(Evidence.claim_id == claim.id)).all()
    items.sort(key=lambda item: (item.evidence_date, item.invoice_number, item.line_index))
    invoices: list[str] = []
    credits = []
    for item in items:
        if item.type == "vendor_credit":
            credits.append(item)
        elif item.amount > 0 and item.type != "tariff_other" and item.invoice_number not in invoices:
            invoices.append(item.invoice_number)
    stored = _loads(vendor.address_json, {})
    address = [line for line in (stored.get("line1"), stored.get("line2")) if line]
    clause = bool(contract.get("refund_or_credit_clause"))
    facts = LetterFacts(
        vendor_name=vendor.name,
        vendor_address=address,
        buyer_name=BUYER_NAME,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        refundable_total=cents(claim.refundable_total),
        credits_already_received=cents(claim.credits_applied),
        credit_memos=[
            f"{item.invoice_number} on {item.evidence_date.isoformat()} for ${cents(-Decimal(str(item.amount))):,.2f}"
            for item in credits
        ],
        invoice_numbers=invoices,
        contract_clause_number=contract.get("clause_number") if clause else None,
        contract_clause_text=contract.get("clause_text") if clause else None,
        signoff=SIGN_OFF,
    )
    return _template(facts, date.today())


def _contract_finding(claim, contract) -> dict:
    return {
        "mentions_tariffs": claim.contract_mentions_tariffs,
        "refund_or_credit_clause": claim.contract_refund_clause,
        "clause_number": claim.clause_number,
        "clause_text": claim.clause_text,
        "summary": contract.summary if contract else None,
        "labeled_by": contract.labeled_by if contract else None,
    }


def _summary(session: Session) -> dict:
    claims = session.exec(select(Claim)).all()
    cards = [_claim_card(session, claim) for claim in claims]
    cards.sort(key=lambda card: (-card["refundable"], card["vendor"]))
    scan = _latest_scan(session)
    usage = _usage_payload(json.loads(scan.usage_json) if scan else {})
    cases = json.loads(scan.importer_json) if scan else []
    importer_total = money_f(sum((Decimal(str(case["amount"])) for case in cases), Decimal("0")))
    return {
        "net_refundable": _sum_field(claims, "refundable_total"),
        "non_refundable": _sum_field(claims, "non_refundable_total"),
        "needs_review_count": scan.needs_review_count if scan else 0,
        "importer_of_record": {"count": len(cases), "total": importer_total, "cases": cases},
        "credits_already_received": _sum_field(claims, "credits_applied"),
        "model_usage": usage,
        "claims": cards,
    }


def _claim_card(session: Session, claim: Claim) -> dict:
    vendor = session.get(Vendor, claim.vendor_id)
    return {
        "vendor_id": claim.vendor_id,
        "vendor": vendor.name if vendor else claim.vendor_id,
        "refundable": money_f(claim.refundable_total),
        "strength": claim.strength,
        "status": claim.status,
        "bill_count": claim.bill_count,
        "subtitle": claim.subtitle,
    }


def _detail(session: Session, vendor: Vendor, claim: Claim) -> dict:
    evidence = session.exec(select(Evidence).where(Evidence.claim_id == claim.id)).all()
    bills = {bill.invoice_number: bill.id for bill in session.exec(select(Bill)).all()}
    letter = session.exec(select(Letter).where(Letter.claim_id == claim.id)).first()
    history = _loads(claim.price_history_json, {})
    received = session.exec(
        select(VendorCredit).where(VendorCredit.vendor_id == vendor.id, VendorCredit.source != "recovery")
    ).all()
    recovery = session.exec(
        select(VendorCredit).where(VendorCredit.vendor_id == vendor.id, VendorCredit.source == "recovery")
    ).all()
    return {
        "vendor_id": vendor.id,
        "vendor": vendor.name,
        "contact_email": vendor.contact_email,
        "strength": claim.strength,
        "status": claim.status,
        "subtitle": claim.subtitle,
        "bill_count": claim.bill_count,
        "refundable": money_f(claim.refundable_total),
        "gross_refundable": money_f(claim.gross_refundable),
        "non_refundable": money_f(claim.non_refundable_total),
        "raw_price_increase": money_f(claim.raw_price_increase),
        "conservative_price_increase": money_f(claim.price_excess_total),
        "price_reverted": claim.price_reverted,
        "evidence_tier": history.get("evidence_tier"),
        "tier_reasons": history.get("tier_reasons") or [],
        "claim_low": history.get("claim_low"),
        "claim_expected": history.get("claim_expected"),
        "claim_high": history.get("claim_high"),
        "origin_inferred_only": bool(history.get("origin_inferred_only")),
        "import_cost_share": history.get("import_cost_share", 0.6),
        "evidence": [
            {
                "invoice_number": item.invoice_number,
                "line_index": item.line_index,
                "date": item.evidence_date.isoformat(),
                "description": item.description,
                "amount": money_f(item.amount),
                "type": item.type,
                "labeled_by": item.labeled_by,
                "bill_id": bills.get(item.invoice_number),
            }
            for item in evidence
        ],
        "price_history": history.get("skus", []),
        "contract": _loads(claim.contract_json, {}),
        "credits_already_received": [_credit_payload(credit) for credit in received],
        "recovery_credits": [_credit_payload(credit) for credit in recovery],
        "letter": _letter_payload(letter) if letter else None,
        "status_history": _loads(claim.status_history_json, []),
    }


def _letter_payload(letter: Letter) -> dict:
    return {
        "body": letter.body,
        "original_body": letter.original_body,
        "status": letter.status,
        "word_count": letter.word_count,
        "model": letter.model,
        "edited": letter.body != letter.original_body,
    }


def _credit_payload(credit: VendorCredit) -> dict:
    return {
        "id": credit.id,
        "vendor_id": credit.vendor_id,
        "credit_memo_number": credit.credit_memo_number,
        "issued_at": credit.issued_at.isoformat(),
        "amount": money_f(credit.amount),
        "status": credit.status,
        "memo": credit.memo,
        "reference": credit.reference,
        "applied_to_bill_id": credit.applied_to_bill_id,
        "source": credit.source,
    }


def _home(session: Session) -> dict:
    hour = datetime.now(LA).hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"
    claims = session.exec(select(Claim)).all()
    open_claims = [claim for claim in claims if claim.refundable_total > 0 and claim.status != "Credited"]
    amount = _sum_field(open_claims, "refundable_total")
    if not claims:
        title = "Scan paid bills for tariff refunds"
        detail = "Look for IEEPA charges suppliers passed through after February 2025."
    elif not open_claims:
        title = "Tariff refunds are on the next bills"
        detail = "Supplier credits are waiting in Bill Pay."
    else:
        noun = "supplier" if len(open_claims) == 1 else "suppliers"
        title = f"{len(open_claims)} {noun} may owe you ${amount:,.2f} in tariff refunds"
        detail = "Review the claim letters before anything is sent."
    return {
        "greeting": greeting,
        "prompt": "What can Ramp help you with?",
        "tasks": [
            {
                "id": "recoveries",
                "title": title,
                "detail": detail,
                "href": "/bill-pay/recoveries",
                "amount": amount if claims else None,
            },
            {
                "id": "receipts",
                "title": "2 bills are waiting on a receipt",
                "detail": "Card transactions from last week still need a receipt.",
                "href": "/expenses",
            },
            {
                "id": "card",
                "title": "Card ending 4412 expires in December",
                "detail": "Replace it before the next team offsite.",
                "href": "/cards",
            },
            {
                "id": "policy",
                "title": "A policy update needs a signature",
                "detail": "The travel policy changed the hotel cap to $275.",
                "href": "/policy",
            },
        ],
    }


def _reset(session: Session) -> dict:
    claims = session.exec(select(Claim)).all()
    letters = session.exec(select(Letter)).all()
    evidence = session.exec(select(Evidence)).all()
    scans = session.exec(select(ScanRun)).all()
    credits = session.exec(select(VendorCredit).where(VendorCredit.source == "recovery")).all()
    for row in (*letters, *evidence, *claims, *scans, *credits):
        session.delete(row)
    for line in session.exec(select(BillLine)).all():
        line.category = None
        line.decision = None
        line.reason = None
        line.labeled_by = None
        session.add(line)
    return {"claims": len(claims), "letters": len(letters), "credits": len(credits), "scans": len(scans)}


def _ingest_uploads(engine, paths: list[Path]) -> tuple[list[dict], list[str]]:
    settings = get_settings()
    parsed = UploadSource(paths, settings).get_bills()
    created: list[dict] = []
    skipped: list[str] = []
    with Session(engine) as session:
        vendors = {vendor.name.casefold(): vendor for vendor in session.exec(select(Vendor)).all()}
        existing = {bill.invoice_number: bill.id for bill in session.exec(select(Bill)).all()}
        for bill in parsed:
            if bill.invoice_number in existing and bill.line_items:
                skipped.append(bill.invoice_number)
                continue
            vendor = vendors.get(bill.vendor.name.casefold())
            if vendor is None and bill.vendor.name != "Unknown vendor":
                vendor = Vendor(id=bill.vendor.id, name=bill.vendor.name)
                session.add(vendor)
                vendors[vendor.name.casefold()] = vendor
            elif vendor is None:
                vendor = Vendor(id=bill.vendor.id, name=bill.vendor.name)
                session.add(vendor)
                vendors[vendor.name.casefold()] = vendor
            if bill.id in {row.id for row in session.exec(select(Bill)).all()}:
                skipped.append(bill.invoice_number)
                continue
            session.add(
                Bill(
                    id=bill.id,
                    vendor_id=vendor.id,
                    invoice_number=bill.invoice_number,
                    issued_at=bill.issued_at,
                    due_at=bill.due_at,
                    paid_at=bill.paid_at,
                    amount=money_f(bill.amount),
                    status="UPLOADED" if bill.needs_review or not bill.line_items else "PAID",
                    document_url=bill.document_url,
                    document_is_scanned_image=bill.document_is_scanned_image,
                    page_count=bill.page_count,
                    needs_review=bill.needs_review,
                    review_reason=bill.review_reason,
                    source="upload",
                )
            )
            for line in bill.line_items:
                session.add(
                    BillLine(
                        bill_id=bill.id,
                        line_index=line.line_index,
                        sku=line.sku,
                        description=line.description,
                        quantity=float(line.quantity),
                        unit_price=money_f(line.unit_price),
                        amount=money_f(line.amount),
                    )
                )
            created.append({"id": bill.id, "invoice_number": bill.invoice_number, "needs_review": bill.needs_review})
        session.commit()
    return created, skipped


def _importer_payload(session: Session, cases) -> list[dict]:
    vendors = {vendor.name: vendor.id for vendor in session.exec(select(Vendor)).all()}
    return [
        {
            "invoice_number": case.invoice_number,
            "line_index": case.line_index,
            "vendor": case.vendor_name,
            "vendor_id": vendors.get(case.vendor_name),
            "issued_at": case.issued_at.isoformat(),
            "description": case.description,
            "amount": money_f(case.amount),
            "guidance": case.guidance,
            "note": CBP_NOTE,
            "labeled_by": case.labeled_by,
        }
        for case in cases
    ]


def _usage_payload(raw: dict) -> dict:
    settings = get_settings()
    tiers = {
        "tier1": _empty_usage(settings.tier1_model),
        "tier2": _empty_usage(settings.tier2_model),
    }

    def bucket(model: str) -> str:
        if model == settings.tier1_model or model.endswith("tier1"):
            return "tier1"
        if model == settings.tier2_model or model.endswith("tier2"):
            return "tier2"
        return model

    calls = raw.get("calls") or {}
    for model, count in calls.items():
        key = bucket(model)
        slot = tiers.setdefault(key, _empty_usage(model))
        if count:
            slot["model"] = model
        slot["calls"] += count
        slot["input_tokens"] += (raw.get("input_tokens") or {}).get(model, 0)
        slot["output_tokens"] += (raw.get("output_tokens") or {}).get(model, 0)
        slot["cache_read_tokens"] += (raw.get("cache_read_tokens") or {}).get(model, 0)
        slot["cache_write_tokens"] += (raw.get("cache_write_tokens") or {}).get(model, 0)
    return tiers


def _empty_usage(model: str) -> dict:
    return {
        "model": model,
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def _scan_payload(scan: ScanRun) -> dict:
    return {
        "id": scan.id,
        "scan_id": scan.id,
        "status": scan.status,
        "step": scan.step,
        "step_index": scan.step_index,
        "step_count": len(STEPS),
        "steps": STEPS,
        "cached": scan.cached,
        "error": scan.error,
    }


def _latest_scan(session: Session) -> ScanRun | None:
    scans = session.exec(select(ScanRun).where(ScanRun.status == "complete")).all()
    if not scans:
        return None
    return max(scans, key=lambda scan: scan.finished_at or scan.created_at)


def _importer_cases(session: Session) -> list[dict]:
    scan = _latest_scan(session)
    if scan is None:
        return []
    return json.loads(scan.importer_json or "[]")


def _claim_for(session: Session, vendor_id: str) -> Claim:
    claim = session.exec(select(Claim).where(Claim.vendor_id == vendor_id)).first()
    if claim is None:
        raise HTTPException(status_code=404, detail="No recovery claim for this vendor.")
    return claim


def _next_unpaid(session: Session, vendor_id: str) -> Bill | None:
    bills = session.exec(select(Bill).where(Bill.vendor_id == vendor_id, Bill.status == "UNPAID")).all()
    open_bills = []
    for bill in bills:
        if _applied_credits(session, bill.id):
            continue
        open_bills.append(bill)
    open_bills.sort(key=lambda bill: (bill.due_at or date.max, bill.invoice_number))
    return open_bills[0] if open_bills else None


def _applied_credits(session: Session, bill_id: str) -> list[dict]:
    credits = session.exec(select(VendorCredit).where(VendorCredit.applied_to_bill_id == bill_id)).all()
    return [_credit_payload(credit) for credit in credits]


def _bill_summary(session: Session, bill: Bill, vendor: Vendor | None) -> dict:
    applied = _applied_credits(session, bill.id)
    credit_total = sum((Decimal(str(credit["amount"])) for credit in applied), Decimal("0"))
    if bill.status == "UNPAID":
        balance = money_f(max(Decimal("0"), cents(bill.amount) - credit_total))
    else:
        balance = 0.0
    return {
        "id": bill.id,
        "vendor_id": bill.vendor_id,
        "vendor": vendor.name if vendor else bill.vendor_id,
        "invoice_number": bill.invoice_number,
        "issued_at": bill.issued_at.isoformat(),
        "due_at": bill.due_at.isoformat() if bill.due_at else None,
        "paid_at": bill.paid_at.isoformat() if bill.paid_at else None,
        "amount": money_f(bill.amount),
        "currency": bill.currency,
        "status": bill.status,
        "balance_due": balance,
        "source": bill.source,
    }


def _vendor_card(vendor: Vendor, claim: Claim | None) -> dict:
    return {
        "id": vendor.id,
        "name": vendor.name,
        "contact_email": vendor.contact_email,
        "bill_count": vendor.bill_count,
        "total_paid": money_f(vendor.total_paid),
        "recovery": None
        if claim is None
        else {
            "refundable": money_f(claim.refundable_total),
            "strength": claim.strength,
            "status": claim.status,
            "subtitle": claim.subtitle,
            "bill_count": claim.bill_count,
        },
    }


def _contract_row(vendor: Vendor, claim: Claim | None) -> dict | None:
    if not vendor.contract_json:
        return None
    stored = json.loads(vendor.contract_json)
    finding = _loads(claim.contract_json, {}) if claim else {}
    return {
        "vendor_id": vendor.id,
        "vendor_name": vendor.name,
        "title": stored.get("title"),
        "effective_date": stored.get("effective_date"),
        "has_tariff_clause": bool(stored.get("has_tariff_clause")),
        "section": stored.get("tariff_clause_section"),
        "clause_number": finding.get("clause_number"),
        "clause_text": finding.get("clause_text"),
        "summary": finding.get("summary"),
        "document_url": f"/api/contracts/{vendor.id}/document",
    }


def _pdf(url: str | None) -> FileResponse:
    path = _resolve_pdf(url)
    if path is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


def _resolve_pdf(url: str | None) -> Path | None:
    if not url:
        return None
    raw = Path(url)
    data_dir = get_settings().resolved_data_dir()
    candidates = [raw, REPO_ROOT / url, data_dir / raw.name, BACKEND_DIR / "uploads" / raw.name]
    allowed = [data_dir.resolve(), (BACKEND_DIR / "uploads").resolve(), (REPO_ROOT / "data").resolve()]
    for candidate in candidates:
        if not candidate.exists() or candidate.suffix.lower() != ".pdf":
            continue
        resolved = candidate.resolve()
        if any(resolved == root or root in resolved.parents for root in allowed):
            return resolved
    return None


def _sum_field(rows, name: str) -> float:
    total = sum((Decimal(str(getattr(row, name))) for row in rows), Decimal("0"))
    return money_f(total)


def _push_status(claim: Claim, status: str) -> None:
    history = _loads(claim.status_history_json, [])
    history.append({"status": status, "at": _stamp()})
    claim.status_history_json = json.dumps(history)


def _word_count(body: str) -> int:
    import re

    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'./$%-]*", body))


app = create_app()
