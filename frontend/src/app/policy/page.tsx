"use client";

import { toast } from "sonner";
import { PrimaryButton } from "@/components/ramp/buttons";
import { DataTable, StatusChip, type Column } from "@/components/ramp/data-table";
import { PageHeader } from "@/components/ramp/page-header";

type Policy = {
  id: string;
  name: string;
  detail: string;
};

const POLICIES: Policy[] = [
  {
    id: "travel",
    name: "Travel policy",
    detail: "Hotel cap is now $275 a night. This update needs a signature.",
  },
];

const columns: Column<Policy>[] = [
  {
    key: "name",
    header: "Policy",
    render: (row) => (
      <span className="block min-w-0">
        <span className="block text-[14px] text-[#1c1c1c]">{row.name}</span>
        <span className="block text-[12px] text-[#8a8680]">{row.detail}</span>
      </span>
    ),
  },
  {
    key: "status",
    header: "Status",
    render: () => <StatusChip label="Needs signature" tone="yellow" />,
  },
  {
    key: "action",
    header: "",
    align: "right",
    render: () => (
      <PrimaryButton className="h-8" onClick={() => toast("Signing policies isn't part of this prototype.")}>
        Sign
      </PrimaryButton>
    ),
  },
];

export default function PolicyPage() {
  return (
    <div className="flex min-h-full flex-col px-8 pt-1 pb-12">
      <PageHeader title="Policy" subtitle="Spend rules for the cafe team." />
      <div className="mt-6">
        <DataTable columns={columns} rows={POLICIES} rowKey={(row) => row.id} footer="1 update waiting" />
      </div>
    </div>
  );
}
