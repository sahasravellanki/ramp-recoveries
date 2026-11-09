"use client";

import { toast } from "sonner";
import { EmptyState } from "@/components/ramp/empty-state";
import { NoticeBanner } from "@/components/ramp/notice-banner";
import { PageHeader } from "@/components/ramp/page-header";

export default function ProcurementPage() {
  return (
    <div className="flex min-h-full flex-col px-8 pt-1 pb-12">
      <PageHeader title="Procurement" />
      <div className="mt-6">
        <NoticeBanner
          tone="yellow"
          title="Purchase requests need an owner"
          detail="Requests sit in draft until someone on the cafe team is set as the approver."
          action="Assign owner"
          onAction={() => toast("Approvers aren't part of this prototype.")}
        />
      </div>
      <div className="flex flex-1 items-center justify-center py-24">
        <EmptyState
          title="No purchase requests"
          subtitle="Requests for equipment and supplies will show up here before they become bills."
          action="New request"
          onAction={() => toast("New request isn't part of this prototype.")}
        />
      </div>
    </div>
  );
}
