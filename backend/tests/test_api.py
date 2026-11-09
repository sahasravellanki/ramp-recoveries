"""API checks against the seeded demo: totals, one credit on the next bill, and reset."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app import create_app
from pipeline.config import REPO_ROOT, get_settings

TRUTH = json.loads((REPO_ROOT / "data" / "ground_truth.json").read_text())
TOTALS = TRUTH["totals"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("RECOVERIES_STEP_DELAY", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    app = create_app(f"sqlite:///{tmp_path}/recoveries.db")
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def _finish(client: TestClient) -> dict:
    started = client.post("/api/recoveries/scan")
    assert started.status_code == 200, started.text
    scan_id = started.json()["scan_id"]
    deadline = time.time() + 90
    last = {}
    while time.time() < deadline:
        response = client.get(f"/api/recoveries/scan/{scan_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in {"complete", "error"}:
            assert last["status"] == "complete", last.get("error")
            return last
        time.sleep(0.05)
    raise AssertionError(f"scan did not finish: {last}")


def test_scan_totals_match_ground_truth(client: TestClient):
    first = _finish(client)
    assert first["steps"] == [
        "reading bills",
        "labeling lines",
        "checking prices",
        "reviewing contracts",
        "building claims",
        "drafting letters",
    ]
    assert first["step"] == "drafting letters"
    assert first["cached"] is False

    body = client.get("/api/recoveries").json()
    assert body["net_refundable"] == pytest.approx(TOTALS["net_claim_total_after_credits"], abs=0.05)
    assert body["non_refundable"] == pytest.approx(TOTALS["non_refundable_total"], abs=0.05)
    assert body["importer_of_record"]["total"] == pytest.approx(TOTALS["importer_of_record_duty_total"], abs=0.05)
    assert body["importer_of_record"]["count"] == 2
    assert body["credits_already_received"] == pytest.approx(500, abs=0.05)
    assert body["needs_review_count"] == 0

    by_name = {claim["vendor"]: claim for claim in body["claims"]}
    assert by_name["Northwind Packaging Co."]["strength"] == "High"
    assert by_name["Northwind Packaging Co."]["subtitle"] == "Tariff Surcharge (12%)"
    assert by_name["Harbor & Pine Coffee Equipment"]["strength"] == "High"
    assert by_name["Harbor & Pine Coffee Equipment"]["subtitle"] == "Price increase"
    assert by_name["Altamesa Electronics Supply"]["strength"] == "Medium"
    assert by_name["Kestrel Textiles"]["strength"] == "Tracked"
    assert "Brightline Office Supply" not in by_name
    assert "Pacific Freight Forwarding" not in by_name

    replay = _finish(client)
    assert replay["cached"] is True


def test_approve_then_simulate_agree_applies_one_credit(client: TestClient):
    _finish(client)
    claims = client.get("/api/recoveries").json()["claims"]
    northwind = next(claim for claim in claims if claim["vendor"] == "Northwind Packaging Co.")
    vendor_id = northwind["vendor_id"]
    unpaid = [
        bill
        for bill in client.get("/api/bills", params={"status": "UNPAID"}).json()
        if bill["vendor_id"] == vendor_id
    ]
    assert len(unpaid) == 1

    approved = client.post(f"/api/recoveries/{vendor_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "Sent"

    agreed = client.post(f"/api/recoveries/{vendor_id}/simulate-agree")
    assert agreed.status_code == 200, agreed.text
    assert agreed.json()["status"] == "Credited"
    assert agreed.json()["applied_to_bill_id"] == unpaid[0]["id"]
    assert agreed.json()["amount"] == pytest.approx(northwind["refundable"], abs=0.01)

    again = client.post(f"/api/recoveries/{vendor_id}/simulate-agree")
    assert again.status_code == 409

    recovery = []
    for vendor in client.get("/api/vendors").json():
        profile = client.get(f"/api/vendors/{vendor['id']}").json()
        recovery.extend(credit for credit in profile["credits"] if credit["source"] == "recovery")
    assert len(recovery) == 1
    assert recovery[0]["applied_to_bill_id"] == unpaid[0]["id"]
    assert recovery[0]["amount"] == pytest.approx(northwind["refundable"], abs=0.01)

    profile = client.get(f"/api/vendors/{vendor_id}").json()
    seed = [credit for credit in profile["credits"] if credit["credit_memo_number"] == "NWP-CM-202603-001"]
    assert len(seed) == 1
    assert seed[0]["source"] == "seed"
    assert seed[0]["applied_to_bill_id"] is None

    bill = client.get(f"/api/bills/{unpaid[0]['id']}").json()
    assert bill["applied_credit"]["id"] == recovery[0]["id"]
    assert bill["balance_due"] == pytest.approx(max(0, bill["amount"] - recovery[0]["amount"]), abs=0.02)
    assert bill["amount"] == unpaid[0]["amount"]


def test_reset_restores_initial_state(client: TestClient):
    initial = client.get("/api/recoveries").json()
    initial_unpaid = client.get("/api/bills", params={"status": "UNPAID"}).json()
    initial_cases = client.get("/api/importer-cases").json()

    _finish(client)
    claims = client.get("/api/recoveries").json()["claims"]
    vendor_id = next(claim["vendor_id"] for claim in claims if claim["vendor"] == "Northwind Packaging Co.")
    edited = "Please apply this as a vendor credit.\n\nAccounts Payable, Sunbird Cafe Group\n"
    saved = client.put(f"/api/recoveries/{vendor_id}/letter", json={"body": edited})
    assert saved.status_code == 200, saved.text
    assert saved.json()["edited"] is True
    assert client.post(f"/api/recoveries/{vendor_id}/approve").status_code == 200
    assert client.post(f"/api/recoveries/{vendor_id}/simulate-agree").status_code == 200
    assert client.get("/api/recoveries").json() != initial

    reset = client.post("/api/demo/reset")
    assert reset.status_code == 200, reset.text
    assert client.get("/api/recoveries").json() == initial
    assert client.get("/api/bills", params={"status": "UNPAID"}).json() == initial_unpaid
    assert client.get("/api/importer-cases").json() == initial_cases
    assert client.get(f"/api/recoveries/{vendor_id}").status_code == 404

    profile = client.get(f"/api/vendors/{vendor_id}").json()
    assert all(credit["source"] != "recovery" for credit in profile["credits"])
    seed = next(credit for credit in profile["credits"] if credit["credit_memo_number"] == "NWP-CM-202603-001")
    assert seed["applied_to_bill_id"] is None
    assert profile["recovery"] is None
