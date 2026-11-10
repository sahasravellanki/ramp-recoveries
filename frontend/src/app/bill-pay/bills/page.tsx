"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { PrimaryButton, SecondaryButton } from "@/components/ramp/buttons";
import { DataTable, Money, StatusChip, VendorCell, type Column } from "@/components/ramp/data-table";
import { EmptyState } from "@/components/ramp/empty-state";
import { PageHeader } from "@/components/ramp/page-header";
import { SearchToolbar } from "@/components/ramp/search-toolbar";
import { formatDate, getBills, initials, usd, type BillSummary } from "@/lib/recoveries";

export default function BillsPage() {
  const [bills, setBills] = useState<BillSummary[] | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    function load() {
      getBills("UNPAID")
        .then((next) => {
          if (!cancelled) setBills(next);
        })
        .catch((error: Error) => {
          if (cancelled) return;
          setBills([]);
          toast.error(error.message);
        });
    }
    load();
    const onReset = () => load();
    window.addEventListener("demo-reset", onReset);
    return () => {
      cancelled = true;
      window.removeEventListener("demo-reset", onReset);
    };
  }, []);

  const visible = (bills ?? []).filter((bill) => {
    const needle = query.trim().toLowerCase();
    if (!needle) return true;
    return `${bill.vendor} ${bill.invoice_number}`.toLowerCase().includes(needle);
  });

  const columns: Column<BillSummary>[] = [
    {
      key: "vendor",
      header: "Vendor",
      render: (bill) => (
        <Link href={`/bill-pay/bills/${bill.id}`} className="block min-w-0">
          <VendorCell name={bill.vendor} subtitle={bill.invoice_number} initials={initials(bill.vendor)} />
        </Link>
      ),
    },
    {
      key: "due",
      header: "Due",
      render: (bill) => <span className="text-[14px] text-[#1c1c1c]">{bill.due_at ? formatDate(bill.due_at) : "—"}</span>,
    },
    {
      key: "status",
      header: "Status",
      render: (bill) => <StatusChip label={bill.balance_due === 0 ? "Covered" : "Unpaid"} tone={bill.balance_due === 0 ? "green" : "yellow"} />,
    },
    {
      key: "amount",
      header: "Amount",
      align: "right",
      render: (bill) => <Money amount={usd(bill.amount).replace("$", "")} />,
    },
    {
      key: "balance",
      header: "Balance",
      align: "right",
      render: (bill) => <Money amount={usd(bill.balance_due).replace("$", "")} />,
    },
  ];

  return (
    <div className="flex min-h-full w-full min-w-0 flex-col px-6 pt-1 pb-12 lg:px-8">
      <PageHeader
        title="Bills"
        breadcrumb={{ label: "Bill Pay", href: "/bill-pay/bills" }}
        actions={
          <>
            <SecondaryButton onClick={() => toast("Recurring bills aren't part of this prototype.")}>
              Recurring bills
            </SecondaryButton>
            <PrimaryButton chevron onClick={() => toast("Creating a bill isn't part of this prototype.")}>
              New bill
            </PrimaryButton>
          </>
        }
      />
      <div className="mt-6">
        <SearchToolbar value={query} onChange={setQuery} />
      </div>
      <div className="mt-4">
        {bills === null ? (
          <p className="mt-10 text-[14px] text-[#6f6c66]">Loading bills…</p>
        ) : (
          <DataTable
            columns={columns}
            rows={visible}
            rowKey={(bill) => bill.id}
            footer={visible.length ? `${visible.length} open ${visible.length === 1 ? "bill" : "bills"}` : undefined}
            empty={<EmptyState title="No open bills" subtitle="Paid bills are what Recoveries scans. Open bills are where a vendor credit lands." />}
          />
        )}
      </div>
    </div>
  );
}
