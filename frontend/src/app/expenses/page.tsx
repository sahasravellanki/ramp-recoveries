"use client";

import { DataTable, Money, StatusChip, VendorCell, type Column } from "@/components/ramp/data-table";
import { PageHeader } from "@/components/ramp/page-header";

type Receipt = {
  id: string;
  merchant: string;
  detail: string;
  amount: string;
};

const WAITING: Receipt[] = [
  { id: "rcpt-1", merchant: "Whole Foods Market", detail: "Card · last Tuesday", amount: "86.40" },
  { id: "rcpt-2", merchant: "Uber", detail: "Card · last Thursday", amount: "24.15" },
];

const columns: Column<Receipt>[] = [
  {
    key: "merchant",
    header: "Transaction",
    render: (row) => <VendorCell name={row.merchant} subtitle={row.detail} initials={row.merchant.slice(0, 2).toUpperCase()} />,
  },
  {
    key: "status",
    header: "Receipt",
    render: () => <StatusChip label="Missing receipt" tone="yellow" />,
  },
  {
    key: "amount",
    header: "Amount",
    align: "right",
    render: (row) => <Money amount={row.amount} />,
  },
];

export default function ExpensesPage() {
  return (
    <div className="flex min-h-full flex-col px-8 pt-1 pb-12">
      <PageHeader title="Expenses" subtitle="2 card transactions from last week still need a receipt." />
      <div className="mt-6">
        <DataTable columns={columns} rows={WAITING} rowKey={(row) => row.id} footer="2 waiting on a receipt" />
      </div>
    </div>
  );
}
