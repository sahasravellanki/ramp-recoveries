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
backend/    FastAPI app (app.py), tariff detection pipeline (pipeline/), eval.py
frontend/   Next.js App Router + TypeScript + Tailwind + shadcn/ui
data/       Generated invoices, contracts, labels, ground truth, Ramp-shaped bills/vendors
scripts/    make_sample_data.py (synthetic data generator)
```

## Stack

- Frontend: Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui
- Backend: FastAPI, Python 3.11+
- Database: SQLite via SQLModel
- AI: Anthropic SDK. Tier 1 (`RECOVERIES_MODEL_TIER1`) = Claude Haiku for line labeling; tier 2 (`RECOVERIES_MODEL_TIER2`) = Claude Sonnet for letter drafting. Both read from env vars.
- Claim math: Decimal. The model never computes a dollar.
- PDF parsing: pdfplumber

## Sample data

All companies, addresses, and prices are fictional. The buyer is Sunbird Cafe Group (Berkeley, CA). The original six suppliers cover an explicit IEEPA surcharge, a price increase with a contract, a renamed surcharge, a Section 301 line, a domestic control, and importer-of-record duty. Eight more are adversarial cases with known answers: surcharge wording the keyword rules miss, a Section 232 surcharge, a price jump from before February 2025, a domestic price jump, a supplier-wide inflation increase, a jump timed to the wrong country's tariff date, a jump timed to a later country's date, and an item whose origin is inferred. Regenerate with:

```bash
python scripts/make_sample_data.py
```

It is seeded, so output is byte-identical every run. It writes `data/invoices/*.pdf` (104 invoices + 1 credit memo, 3 rendered as scans, 1 two-pager), `data/contracts/*.pdf`, `data/labels.csv`, `data/ground_truth.json`, `data/bills.json`, `data/vendors.json`, and `data/vendor_credits.json`, then prints the expected claim totals.

## Running locally

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --reload --port 8471
```

On startup the API loads `data/` into `recoveries.db` when that database is empty, including one unpaid upcoming bill for each vendor that has a claim. `POST /api/recoveries/scan` runs the pipeline in the background. The first scan does the work; a replay uses the cached result and still walks the progress steps. `DEMO_MODE=1` (or no API key) keeps labeling on the keyword rules.

```bash
cd backend
python -m pytest tests -q
```

Frontend:

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

The frontend runs on http://localhost:4817 and expects the backend at `NEXT_PUBLIC_API_URL` (http://localhost:8471). The shell matches the Ramp app: Home loads its task feed from `GET /api/home`, and the avatar menu resets the demo. Bill Pay → Recoveries is at `/bill-pay/recoveries`.

## Tariff table

Refundable rates live in `backend/pipeline/tariffs.py`. A price claim uses the rate in effect on the day the price jumped. Section 232 and Section 301 are in the table and are not refundable.

| Action | Dates | Rate | Source |
| --- | --- | --- | --- |
| China fentanyl IEEPA | Feb 4, 2025 – Mar 3, 2025 | 10% | [CBP factsheet, May 2, 2025](https://www.cbp.gov/sites/default/files/2025-05/new_tariff_requirements_2025_factsheet_05-02-25.pdf) |
| China fentanyl IEEPA | Mar 4, 2025 on | 20% | [CBP statement on tariffs](https://www.cbp.gov/newsroom/announcements/official-cbp-statement-tariffs) |
| Canada, non-USMCA | Mar 4, 2025 on | 25% | [CBP statement on tariffs](https://www.cbp.gov/newsroom/announcements/official-cbp-statement-tariffs) |
| Mexico, non-USMCA | Mar 4, 2025 on | 25% | [CBP factsheet, May 2, 2025](https://www.cbp.gov/sites/default/files/2025-05/new_tariff_requirements_2025_factsheet_05-02-25.pdf) |
| Reciprocal baseline, except Canada and Mexico | Apr 5, 2025 – Aug 6, 2025 | 10% | [EO 14257, 90 FR 15041](https://www.federalregister.gov/documents/2025/04/07/2025-06063/regulating-imports-with-a-reciprocal-tariff-to-rectify-trade-practices-that-contribute-to-large-and) and [CSMS 64649265](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3da7831). Country-specific rates were suspended April 10; [CSMS 65573545](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3e892a9) extended that 10% through August 1. |
| China reciprocal | Apr 5–8, 2025 | 10%, stacked on the fentanyl tariff | [CSMS 64649265](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3da7831) |
| China reciprocal | Apr 9, 2025 | 84%, stacked | [CBP IEEPA FAQ](https://www.cbp.gov/trade/programs-administration/trade-remedies/IEEPA-FAQ) |
| China reciprocal | Apr 10 – May 13, 2025 | 125%, stacked | [EO 14266, 90 FR 15625](https://www.federalregister.gov/documents/2025/04/15/2025-06462/modifying-reciprocal-tariff-rates-to-reflect-trading-partner-retaliation-and-alignment) |
| China reciprocal | May 14, 2025 on | 10%, stacked on the 20% fentanyl tariff | [EO 14298](https://www.whitehouse.gov/presidential-actions/2025/05/modifying-reciprocal-tariff-rates-to-reflect-discussions-with-the-peoples-republic-of-china/). [CSMS 65829726](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ec7b5e) leaves this 10% in place on August 7. |
| Country-specific reciprocal | Aug 7, 2025 on | Annex I of EO 14326. Vietnam is 20%. A country not listed stays at 10%. | [EO 14326](https://www.whitehouse.gov/presidential-actions/2025/07/further-modifying-the-reciprocal-tariff-rates/) |
| European Union | Aug 7, 2025 on | 15% in this table | Same order. The legal extra duty is 15% minus the Column 1 rate, and zero when Column 1 is already 15% or more. The sample has no Column 1 rate, so the table uses 15%. |
| Section 232 steel and aluminum | not IEEPA | not refundable | [CBP Section 232](https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel) |
| Section 301 | not IEEPA | not refundable | [CBP Section 301](https://www.cbp.gov/trade/programs-administration/entry-summary/section-301-trade-remedies) |

Canada and Mexico use the non-USMCA rate. USMCA-qualifying goods, and the 10% rates on energy and potash, are not modeled. Goods already subject to Section 232 are exempt from the reciprocal tariff; that exemption is not applied SKU by SKU. Rates changed again after the August 7 notice. This table stops at the last rate cited above.

A price increase counts only when the origin had an IEEPA tariff on the invoice date, the jump started 0 to 90 days after that country's first IEEPA date, the per-unit jump is no larger than the rate times a 0.6 import-cost share, and the supplier's domestic or unaffected goods did not rise by a similar amount. The claim is the gap versus that control group. Low is half of it. High is the raw jump. A later price drop is recorded and is not required. An origin the invoice does not state is marked inferred, and a claim built only on that inference is Low strength.

## Pipeline

The tariff pass-through pipeline lives in `backend/pipeline`. With `DEMO_MODE=1` (the default when no API key is set) it labels lines with keyword rules and drafts letters from a template, so it runs with no network access.

```bash
cd backend
python -m pipeline.run
python -m pipeline.eval
```

`pipeline.run` reads `data/bills.json`, prints a claim per vendor, drafts the letters (nothing is sent), and checks demo totals against `data/ground_truth.json`. `pipeline.eval` prints precision and recall for flagged lines and flagged price items, the false-positive dollars on each trap, and the dollar error per vendor. Demo mode misses the three wording traps on purpose. A real-model run happens only when `ANTHROPIC_API_KEY` is set.

## Status

Sample data, the pipeline, the Recoveries API, the app shell, and the Recoveries screen are in place. Open `/bill-pay/recoveries`, scan the paid bills, review a claim, approve the letter, and simulate the supplier agreeing.
