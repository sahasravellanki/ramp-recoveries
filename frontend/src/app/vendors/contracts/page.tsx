"use client";

import { PlaceholderPage } from "@/components/ramp/placeholder-page";

export default function ContractsPage() {
  return (
    <PlaceholderPage
      title="Contracts"
      breadcrumb={{ label: "Vendors", href: "/vendors" }}
      emptyTitle="No contracts uploaded"
      subtitle="Supply agreements land here. Recoveries reads them for a tariff refund clause."
      action="Upload a contract"
    />
  );
}
