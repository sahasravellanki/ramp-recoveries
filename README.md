# Ramp Recoveries

Ramp Recoveries reads a company's paid bills, finds IEEPA tariff costs suppliers passed through in 2025, and drafts a claim letter a person approves before anything is sent. Once the supplier agrees, the credit lands on the next bill. On a synthetic test set with known answers, the model run recovers **$12,689.86**, matching the answer key. Keyword rules miss three relabeled Lumen lines and stop at **$11,684.86**.

## Results

This is a synthetic test set we built with known answers. Every company, invoice, and price is fictional. The buyer is Sunbird Cafe Group. Expected dollars come from `data/ground_truth.json`. Rules-only is the keyword pipeline. The model column is one live run.

Net refundable, after the $500 credit already on file: expected **$12,689.86**, model **$12,689.86**, rules-only **$11,684.86**.

| Vendor | Expected | Model found | Rules-only found | Model error |
| --- | ---: | ---: | ---: | ---: |
| Northwind Packaging Co. | $4,606.40 | $4,606.40 | $4,606.40 | $0.00 |
| Harbor & Pine Coffee Equipment | $3,665.16 | $3,665.16 | $3,665.16 | $0.00 |
| Altamesa Electronics Supply | $3,841.30 | $3,841.30 | $3,841.30 | $0.00 |
| Kestrel Textiles | $0.00 | $0.00 | $0.00 | $0.00 |
| Brightline Office Supply | $0.00 | $0.00 | $0.00 | $0.00 |
| Pacific Freight Forwarding | $0.00 | $0.00 | $0.00 | $0.00 |
| Lumen Sourcing Co. | $1,005.00 | $1,005.00 | $0.00 | $0.00 |
| Mill & Alloy | $0.00 | $0.00 | $0.00 | $0.00 |
| Early Rise Paper | $0.00 | $0.00 | $0.00 | $0.00 |
| Homestead Kiln | $0.00 | $0.00 | $0.00 | $0.00 |
| Level Pantry | $0.00 | $0.00 | $0.00 | $0.00 |
| Calendar Imports | $0.00 | $0.00 | $0.00 | $0.00 |
| Mekong Tabletop | $32.00 | $32.00 | $32.00 | $0.00 |
| Guesswork Goods | $40.00 | $40.00 | $40.00 | $0.00 |
| Clearpour Glass | $0.00 | $0.00 | $0.00 | $0.00 |
| Orchard Copper | $0.00 | $0.00 | $0.00 | $0.00 |

A trap is caught when the refundable dollars match the answer key within $0.05. Clearpour Glass matches on dollars: both paths claim $0, and the model also marks that case Needs review.

| Trap | Vendor | Should count | Expected | Rules-only | Model | Rules-only result | Model result |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| wording | Lumen Sourcing Co. | yes | $1,005.00 | $0.00 | $1,005.00 | missed | caught |
| section_232 | Mill & Alloy | no | $0.00 | $0.00 | $0.00 | caught | caught |
| early_jump | Early Rise Paper | no | $0.00 | $0.00 | $0.00 | caught | caught |
| domestic | Homestead Kiln | no | $0.00 | $0.00 | $0.00 | caught | caught |
| inflation | Level Pantry | no | $0.00 | $0.00 | $0.00 | caught | caught |
| wrong_date | Calendar Imports | no | $0.00 | $0.00 | $0.00 | caught | caught |
| later_date | Mekong Tabletop | yes | $32.00 | $32.00 | $32.00 | caught | caught |
| inferred_origin | Guesswork Goods | yes | $40.00 | $40.00 | $40.00 | caught | caught |
| peer_control | Clearpour Glass | no | $0.00 | $0.00 | $0.00 | caught | needs review, $0 claimed |
| no_control | Orchard Copper | no | $0.00 | $0.00 | $0.00 | caught | caught |

Lumen Sourcing Co. is the wording case. Three lines never say "tariff": "Q3 landed cost adjustment" ($420), "Supplier cost pass-through" ($310), and "Global sourcing fee" ($275). Keyword rules label all three as product and find **$0**. The model relabels each one `tariff_ieepa` and finds **$1,005**.

| Line | Amount | Rules-only label | Model label |
| --- | ---: | --- | --- |
| Q3 landed cost adjustment | $420.00 | product | tariff_ieepa |
| Supplier cost pass-through | $310.00 | product | tariff_ieepa |
| Global sourcing fee | $275.00 | product | tariff_ieepa |

## Running it

Ships with a saved real-model run. It works with no API key. Add `ANTHROPIC_API_KEY` to `backend/.env` to re-run live.

Labeling uses `claude-haiku-4-5`. Hard lines and letters use `claude-sonnet-4-5`. Plain code does the dollar math. Nothing is sent without a person approving the letter.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --reload --port 8471
```

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

The frontend runs on http://localhost:4817 and expects the backend at `NEXT_PUBLIC_API_URL` (http://localhost:8471). Bill Pay → Recoveries is at `/bill-pay/recoveries`. On an empty database the API loads `data/`, then `data/live_results/`, so the screen opens on the saved scan. Scan calls the models only when a key is set.

## Design rules

- AI reads and labels; plain code does all dollar math.
- Every flagged dollar links to an invoice number and line.
- Nothing is sent without human approval.

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
- AI: Anthropic SDK. `claude-haiku-4-5` labels lines. `claude-sonnet-4-5` reviews hard lines and drafts letters. Override with `RECOVERIES_MODEL_TIER1` and `RECOVERIES_MODEL_TIER2`.
- Claim math: Decimal. The model never computes a dollar.
- PDF parsing: pdfplumber

## Sample data

All companies, addresses, and prices are fictional. The buyer is Sunbird Cafe Group (Berkeley, CA). The original six suppliers cover an explicit IEEPA surcharge, a price increase with a contract, a renamed surcharge, a Section 301 line, a domestic control, and importer-of-record duty. Ten more are adversarial cases with known answers: surcharge wording the keyword rules miss, a Section 232 surcharge, a price jump from before February 2025, a domestic price jump, a supplier-wide inflation increase, a jump timed to the wrong country's tariff date, a jump timed to a later country's rate increase, an item whose origin is inferred, an imported item whose only control is the same category at another supplier, and an imported item with no control group at all. Regenerate with:

```bash
python scripts/make_sample_data.py
```

It is seeded, so output is byte-identical every run. It writes `data/invoices/*.pdf` (104 invoices + 1 credit memo, 3 rendered as scans, 1 two-pager), `data/contracts/*.pdf`, `data/labels.csv`, `data/ground_truth.json`, `data/bills.json`, `data/vendors.json`, and `data/vendor_credits.json`, then prints the expected claim totals.

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

A price increase counts only when the origin had an IEEPA tariff on the invoice date, the jump started 0 to 90 days after any IEEPA rate increase for that country, and the item outpaced unaffected goods by more than 2 points. The checklist names the rate increase the jump matched and states that 2-point rule. The control group is the supplier's own domestic or unaffected items. If that supplier has none, the same product category from other suppliers is the control. If no control exists, the item is marked Needs review and is not claimed. The size cap is the tariff rate times the import-cost share times the pre-tariff price. A jump above that cap is still claimed, up to the cap, and the checklist says "Capped at the estimated tariff on import cost." A jump more than twice the cap fails. The review sheet states the assumption, "import cost is about 60% of price," and editing that percent recalculates the cap and the claim. The claim is the gap versus the control group, limited to the cap. Low is half of it. High is the raw jump. A later price drop is recorded and is not required. An origin the invoice does not state is marked inferred, and a claim built only on that inference is Low strength.

## Pipeline

The tariff pass-through pipeline lives in `backend/pipeline`. With no API key the API serves `data/live_results/`. Set `DEMO_MODE=1` in `backend/.env` to skip the models and label with keyword rules and template letters instead. That path makes no network calls. Keyword rules miss the three Lumen wording lines on purpose. The API tests use this mode.

```bash
cd backend
python -m pipeline.run
python -m pipeline.eval
python -m pytest tests -q
```

`pipeline.run` reads `data/bills.json`, prints a claim per vendor, drafts the letters (nothing is sent), and checks totals against `data/ground_truth.json`. `pipeline.eval` prints precision and recall for flagged lines and flagged price items, the false-positive dollars on each trap, and the dollar error per vendor. Keyword rules miss the three wording traps on purpose. A real-model run happens only when `ANTHROPIC_API_KEY` is set and `DEMO_MODE` is unset; that run writes `data/eval_results.md` and `data/live_results/`.

## Status

Sample data, the pipeline, the Recoveries API, the app shell, and the Recoveries screen are in place. Open `/bill-pay/recoveries`, scan the paid bills, review a claim, approve the letter, and simulate the supplier agreeing.
