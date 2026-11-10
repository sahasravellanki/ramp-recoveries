"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { SecondaryButton } from "@/components/ramp/buttons";
import { DataTable, StatusChip, VendorCell, type Column } from "@/components/ramp/data-table";
import { EmptyState } from "@/components/ramp/empty-state";
import { PageHeader } from "@/components/ramp/page-header";
import { contractDocumentUrl, formatDate, getContracts, initials, type ContractRow } from "@/lib/recoveries";

export default function ContractsPage() {
  const [rows, setRows] = useState<ContractRow[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getContracts()
      .then((next) => {
        setRows(next);
        setFailed(false);
      })
      .catch((error: Error) => {
        setRows([]);
        setFailed(true);
        toast.error(error.message);
      });
  }, []);

  const columns: Column<ContractRow>[] = [
    {
      key: "vendor",
      header: "Vendor",
      render: (row) => (
        <VendorCell name={row.vendor_name} subtitle={row.title ?? undefined} initials={initials(row.vendor_name)} />
      ),
    },
    {
      key: "date",
      header: "Effective",
      render: (row) => (
        <span className="text-[14px] text-[#1c1c1c]">{row.effective_date ? formatDate(row.effective_date) : "—"}</span>
      ),
    },
    {
      key: "clause",
      header: "Tariff clause",
      render: (row) => (
        <StatusChip label={row.has_tariff_clause ? "Refund clause" : "No clause"} tone={row.has_tariff_clause ? "green" : "gray"} />
      ),
    },
    {
      key: "section",
      header: "Section",
      render: (row) => <span className="text-[13px] text-[#3f3f3f]">{row.section ?? "—"}</span>,
    },
    {
      key: "doc",
      header: "",
      align: "right",
      render: (row) => (
        <SecondaryButton
          className="h-8 px-3"
          onClick={() => window.open(contractDocumentUrl(row.vendor_id), "_blank", "noopener")}
        >
          Open PDF
        </SecondaryButton>
      ),
    },
  ];

  return (
    <div className="flex min-h-full flex-col px-8 pt-1 pb-12">
      <PageHeader title="Contracts" breadcrumb={{ label: "Vendors", href: "/vendors" }} />
      {rows === null ? (
        <p className="mt-10 text-[14px] text-[#6f6c66]">Loading contracts…</p>
      ) : rows.length === 0 ? (
        <div className="flex flex-1 items-center justify-center py-24">
          <EmptyState
            title={failed ? "Contracts didn't load" : "No contracts uploaded"}
            subtitle="Supply agreements land here. Recoveries reads them for a tariff refund clause."
            action="Upload a contract"
            onAction={() => toast("Uploading a contract isn't part of this prototype.")}
          />
        </div>
      ) : (
        <div className="mt-6">
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(row) => row.vendor_id}
            footer={`${rows.length} contract${rows.length === 1 ? "" : "s"}`}
          />
        </div>
      )}
    </div>
  );
}
