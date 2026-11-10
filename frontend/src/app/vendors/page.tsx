"use client";

import { Download, MoreVertical, Table2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { IconButton, PrimaryButton, SecondaryButton } from "@/components/ramp/buttons";
import { DataTable, Money, StatusChip, VendorCell, type Column } from "@/components/ramp/data-table";
import { EmptyState } from "@/components/ramp/empty-state";
import { NoticeBanner } from "@/components/ramp/notice-banner";
import { PageHeader } from "@/components/ramp/page-header";
import { SearchToolbar } from "@/components/ramp/search-toolbar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { getVendors, initials, usd, type VendorSummary } from "@/lib/recoveries";

export default function VendorsPage() {
  const [vendors, setVendors] = useState<VendorSummary[] | null>(null);
  const [query, setQuery] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getVendors()
      .then((rows) => {
        setVendors(rows);
        setFailed(false);
      })
      .catch((error: Error) => {
        setVendors([]);
        setFailed(true);
        toast.error(error.message);
      });
  }, []);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (vendors ?? []).filter((vendor) => {
      if (!needle) return true;
      return `${vendor.name} ${vendor.contact_email ?? ""}`.toLowerCase().includes(needle);
    });
  }, [vendors, query]);

  const columns: Column<VendorSummary>[] = [
    {
      key: "name",
      header: "Vendor",
      render: (vendor) => (
        <VendorCell name={vendor.name} subtitle={vendor.contact_email ?? undefined} initials={initials(vendor.name)} />
      ),
    },
    {
      key: "bills",
      header: "Bills",
      align: "right",
      render: (vendor) => <span className="text-[14px] tabular-nums text-[#1c1c1c]">{vendor.bill_count}</span>,
    },
    {
      key: "paid",
      header: "Paid",
      align: "right",
      render: (vendor) => <Money amount={usd(vendor.total_paid).replace("$", "")} />,
    },
    {
      key: "recovery",
      header: "Recovery",
      render: (vendor) =>
        vendor.recovery ? (
          <StatusChip
            label={vendor.recovery.status}
            tone={vendor.recovery.status === "Needs review" ? "yellow" : vendor.recovery.status === "Credited" ? "green" : "blue"}
          />
        ) : (
          <span className="text-[13px] text-[#8a8680]">No claim</span>
        ),
    },
  ];

  return (
    <div className="flex min-h-full flex-col px-8 pt-1 pb-10">
      <PageHeader
        title="Vendors"
        actions={
          <>
            <IconButton aria-label="More" onClick={() => toast("More vendor actions aren't part of this prototype.")}>
              <MoreVertical className="size-4" />
            </IconButton>
            <SecondaryButton onClick={() => toast("1099 review isn't part of this prototype.")}>
              Review 1099s
            </SecondaryButton>
            <DropdownMenu>
              <DropdownMenuTrigger render={<PrimaryButton chevron>New vendor</PrimaryButton>} />
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => toast("Creating a vendor isn't part of this prototype.")}>
                  Create a vendor
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => toast("CSV import isn't part of this prototype.")}>
                  Import from CSV
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        }
      />

      <div className="mt-6">
        <NoticeBanner
          tone="green"
          title="Save time on vendor reviews"
          detail="Auto approve W-9s and tax detail updates from the Vendor Network"
          action="Turn on"
          onAction={() => toast("Vendor Network isn't connected in this prototype.")}
        />
      </div>

      <div className="mt-4 border-b border-[#f0eeea] pb-4">
        <SearchToolbar
          value={query}
          onChange={setQuery}
          actions={
            <>
              <IconButton aria-label="Columns">
                <Table2 className="size-4" />
              </IconButton>
              <IconButton aria-label="Download">
                <Download className="size-4" />
              </IconButton>
            </>
          }
        />
      </div>

      {vendors === null ? (
        <p className="mt-10 text-[14px] text-[#6f6c66]">Loading vendors…</p>
      ) : visible.length === 0 ? (
        <div className="flex flex-1 items-center justify-center py-24">
          <EmptyState
            title={failed ? "Vendors didn't load" : query ? "No vendors match" : "No vendors yet"}
            subtitle={
              failed
                ? "The vendor list didn't come back. Check that the API is running."
                : "Add vendors to manage their details and uncover pricing insights"
            }
            action="Import vendors with CSV"
            onAction={() => toast("CSV import isn't part of this prototype.")}
          />
        </div>
      ) : (
        <DataTable
          columns={columns}
          rows={visible}
          rowKey={(vendor) => vendor.id}
          footer={`${visible.length} vendor${visible.length === 1 ? "" : "s"}`}
        />
      )}
    </div>
  );
}
