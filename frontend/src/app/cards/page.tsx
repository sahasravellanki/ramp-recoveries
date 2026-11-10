"use client";

import { DataTable, StatusChip, VendorCell, type Column } from "@/components/ramp/data-table";
import { PageHeader } from "@/components/ramp/page-header";

type Card = {
  id: string;
  name: string;
  detail: string;
  status: string;
};

const CARDS: Card[] = [
  {
    id: "4412",
    name: "Team card · 4412",
    detail: "Sunbird Cafe Group · expires December 2026",
    status: "Expires in December",
  },
];

const columns: Column<Card>[] = [
  {
    key: "name",
    header: "Card",
    render: (row) => <VendorCell name={row.name} subtitle={row.detail} initials="SC" />,
  },
  {
    key: "status",
    header: "Status",
    render: (row) => <StatusChip label={row.status} tone="yellow" />,
  },
];

export default function CardsPage() {
  return (
    <div className="flex min-h-full flex-col px-8 pt-1 pb-12">
      <PageHeader title="Cards and expenses" subtitle="Replace the card ending 4412 before the next team offsite." />
      <div className="mt-6">
        <DataTable columns={columns} rows={CARDS} rowKey={(row) => row.id} footer="1 card expiring" />
      </div>
    </div>
  );
}
