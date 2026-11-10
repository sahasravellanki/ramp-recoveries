# Eval results

Models: tier 1 `claude-haiku-4-5`, tier 2 `claude-sonnet-4-5`.
Rules-only is the keyword pipeline (`DEMO_MODE=1`). The model run is the same bills with the API key set.
A trap is caught when the refundable dollars match the answer key within $0.05.

## Per vendor

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

## Net refundable

Expected, after the $500 credit already on file: **$12,689.86**.
Model found: **$12,689.86** (error $0.00).
Rules-only found: **$11,684.86** (answer for that mode $11,684.86).

## Traps

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
| peer_control | Clearpour Glass | no | $0.00 | $0.00 | $0.00 | caught | WRONG needs review |
| no_control | Orchard Copper | no | $0.00 | $0.00 | $0.00 | caught | caught |

## Lumen wording

Lumen Sourcing Co. hides $1,005 of IEEPA across three lines. Rules-only is built to miss all three. The model run is scored on whether it labels them `tariff_ieepa`.

| Line | Amount | Rules-only label | Model label | Model labeled by |
| --- | ---: | --- | --- | --- |
| Q3 landed cost adjustment | $420.00 | product | tariff_ieepa | claude-sonnet-4-5 |
| Supplier cost pass-through | $310.00 | product | tariff_ieepa | claude-sonnet-4-5 |
| Global sourcing fee | $275.00 | product | tariff_ieepa | claude-sonnet-4-5 |

Rules-only caught 0 of 3. Model caught 3 of 3.
