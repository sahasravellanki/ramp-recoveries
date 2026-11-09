"use client";

import { PlaceholderPage } from "@/components/ramp/placeholder-page";

export default function AccountingPage() {
  return (
    <PlaceholderPage
      title="Accounting"
      emptyTitle="Nothing to sync"
      subtitle="Coded bills and card transactions will queue here before they export to the ledger."
      action="Connect accounting"
    />
  );
}
