"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { StatusChip } from "@/components/ramp/data-table";
import { PageHeader } from "@/components/ramp/page-header";
import { SecondaryButton } from "@/components/ramp/buttons";
import { billDocumentUrl, getBill, usd, type BillDetail } from "@/lib/recoveries";

export function BillView({ id }: { id: string }) {
  const [bill, setBill] = useState<BillDetail | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    getBill(id)
      .then(setBill)
      .catch((error: Error) => {
        setMissing(true);
        toast.error(error.message);
      });
  }, [id]);

  if (missing) {
    return (
      <div className="px-6 pt-6 lg:px-8">
        <p className="text-[14px] text-[#6f6c66]">That bill isn’t in Bill Pay.</p>
      </div>
    );
  }

  if (!bill) {
    return (
      <div className="px-6 pt-6 lg:px-8">
        <p className="text-[14px] text-[#6f6c66]">Loading the bill…</p>
      </div>
    );
  }

  const credits = bill.applied_credits ?? [];
  const covered = bill.balance_due === 0 && credits.length > 0;

  return (
    <div className="flex min-h-full w-full min-w-0 flex-col px-6 pt-1 pb-12 lg:px-8">
      <PageHeader
        title={bill.invoice_number}
        subtitle={bill.vendor}
        breadcrumb={{ label: "Bills", href: "/bill-pay/bills" }}
        actions={
          bill.document_url ? (
            <SecondaryButton onClick={() => window.open(billDocumentUrl(bill.id), "_blank", "noopener")}>
              Invoice PDF
            </SecondaryButton>
          ) : null
        }
      />

      <div className="mt-6 flex flex-wrap items-center gap-3 text-[13px] text-[#6f6c66]">
        <StatusChip label={covered ? "Covered" : bill.status === "UNPAID" ? "Unpaid" : bill.status} tone={covered ? "green" : "yellow"} />
        <span>Issued {bill.issued_at}</span>
        {bill.due_at ? <span>Due {bill.due_at}</span> : null}
      </div>

      {credits.length > 0 ? (
        <div className="mt-5 rounded-md border border-[#c5e3bf] bg-[#f2faef] px-4 py-3">
          <p className="text-[14px] font-medium text-[#1c1c1c]">Vendor credit applied</p>
          <ul className="mt-2 space-y-1">
            {credits.map((credit) => (
              <li key={credit.id} className="text-[13px] text-[#1c1c1c]">
                <span className="font-medium tabular-nums">{usd(credit.amount)}</span>
                {" · "}
                {credit.credit_memo_number}
                {credit.memo ? <span className="text-[#3f3f3f]"> · {credit.memo}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-6 overflow-hidden rounded-lg border border-[#eeeae4]">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-[#eeeae4] text-[12px] text-[#8a8680]">
              <th className="h-10 px-4 font-medium">Item</th>
              <th className="h-10 px-4 text-right font-medium">Qty</th>
              <th className="h-10 px-4 text-right font-medium">Price</th>
              <th className="h-10 px-4 text-right font-medium">Amount</th>
            </tr>
          </thead>
          <tbody>
            {bill.line_items.map((line) => (
              <tr key={line.line_index} className="border-b border-[#f1efe9]">
                <td className="px-4 py-3 text-[14px] text-[#1c1c1c]">{line.description}</td>
                <td className="px-4 py-3 text-right text-[14px] tabular-nums">{line.quantity}</td>
                <td className="px-4 py-3 text-right text-[14px] tabular-nums">{usd(line.unit_price)}</td>
                <td className="px-4 py-3 text-right text-[14px] tabular-nums">{usd(line.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <dl className="space-y-2 px-4 py-4 text-[14px]">
          <div className="flex justify-between gap-4">
            <dt className="text-[#6f6c66]">Bill amount</dt>
            <dd className="tabular-nums text-[#1c1c1c]">{usd(bill.amount)}</dd>
          </div>
          {credits.map((credit) => (
            <div key={credit.id} className="flex justify-between gap-4">
              <dt className="text-[#1c7a42]">Vendor credit {credit.credit_memo_number}</dt>
              <dd className="tabular-nums text-[#1c7a42]">−{usd(credit.amount)}</dd>
            </div>
          ))}
          <div className="flex justify-between gap-4 border-t border-[#eeeae4] pt-2 text-[16px]">
            <dt className="text-[#1c1c1c]">Balance due</dt>
            <dd className="tabular-nums text-[#1c1c1c]">{usd(bill.balance_due)}</dd>
          </div>
        </dl>
      </div>

      <p className="mt-4 text-[13px] text-[#8a8680]">
        <Link href="/bill-pay/bills" className="underline decoration-[#d5d1c8] underline-offset-2">
          Back to bills
        </Link>
      </p>
    </div>
  );
}
