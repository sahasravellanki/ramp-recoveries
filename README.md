# Ramp Recoveries

Hackathon prototype for the BBS x Ramp Hackathon. Ramp Recoveries is a feature inside a Ramp-style spend management app that recovers IEEPA tariff pass-through costs from suppliers.

In 2025, suppliers passed IEEPA tariff costs on to business customers through invoice surcharges and price increases. In February 2026 the Supreme Court struck those tariffs down and importers are receiving refunds, but the businesses that actually paid the higher prices get nothing unless they ask. Ramp Recoveries scans a company's paid bills, finds tariff pass-throughs, totals what each supplier may owe, drafts a claim letter for a human to approve, and, once the supplier agrees, creates a vendor credit in Bill Pay that applies to the next bill.

Everything in the app shell is a static mockup except Recoveries, which fully works.

## Design rules

- AI reads and labels; plain code does all dollar math.
- Every flagged dollar links to an invoice number and line.
- Nothing is sent without human approval.
- `DEMO_MODE=1` (or no API key) uses keyword rules and template letters so the demo never breaks.

## Repo layout

```
backend/    FastAPI app (app/), tariff detection pipeline (pipeline/), eval.py
frontend/   Next.js App Router + TypeScript + Tailwind + shadcn/ui
data/       Generated invoices, contracts, and labels
scripts/    Synthetic data generator
```

## Stack

- Frontend: Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui
- Backend: FastAPI, Python 3.11+
- Database: SQLite via SQLModel
- AI: Anthropic SDK. Tier 1 (`RECOVERIES_MODEL_TIER1`) = Claude Haiku for line labeling; tier 2 (`RECOVERIES_MODEL_TIER2`) = Claude Sonnet for letter drafting. Both read from env vars.
- Math: pandas
- PDF parsing: pdfplumber

## Running locally

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8471
```

Frontend:

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

The frontend runs on http://localhost:4817 and expects the backend on http://127.0.0.1:8471.

## Status

Scaffold only. Pipeline, API, data generator, and UI are not yet implemented.
