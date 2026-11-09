"use client";

import { toast } from "sonner";
import { PrimaryButton, SecondaryButton } from "@/components/ramp/buttons";
import { EmptyState } from "@/components/ramp/empty-state";
import { PageHeader } from "@/components/ramp/page-header";
import { SearchToolbar } from "@/components/ramp/search-toolbar";

export default function BillsPage() {
  return (
    <div className="flex min-h-full flex-col px-8 pt-1 pb-12">
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
        <SearchToolbar />
      </div>
      <div className="flex flex-1 items-center justify-center py-24">
        <EmptyState
          title="No bills yet"
          subtitle="Forward an invoice or create one. Paid bills are what Recoveries scans for tariff pass-throughs."
          action="New bill"
          onAction={() => toast("Creating a bill isn't part of this prototype.")}
        />
      </div>
    </div>
  );
}
