"""Lines where the buyer paid Customs directly are not the supplier's to refund.

A freight forwarder billing "customs duty paid on entry" means Sunbird was the
importer of record. That money comes back from CBP through the entry, so it is
kept out of the supplier claim.
"""

from __future__ import annotations

from .models import Bill, ImporterCase, LineCategory, LineLabel

GUIDANCE = "You are the importer of record. Request this refund from CBP, not from the supplier."


def find_cases(bills: list[Bill], labels: list[LineLabel]) -> list[ImporterCase]:
    label_of = {(label.invoice_number, label.line_index): label for label in labels}
    cases: list[ImporterCase] = []
    for bill in bills:
        for line in bill.line_items:
            label = label_of.get((bill.invoice_number, line.line_index))
            if label is None or label.category is not LineCategory.customs_duty_paid_by_buyer:
                continue
            cases.append(
                ImporterCase(
                    invoice_number=bill.invoice_number,
                    line_index=line.line_index,
                    vendor_name=bill.vendor.name,
                    issued_at=bill.issued_at,
                    description=line.description,
                    amount=line.amount,
                    guidance=GUIDANCE,
                    labeled_by=label.labeled_by,
                )
            )
    return cases
