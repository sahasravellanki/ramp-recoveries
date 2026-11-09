"use client";

import { PlaceholderPage } from "@/components/ramp/placeholder-page";

export default function ExpensesPage() {
  return (
    <PlaceholderPage
      title="Expenses"
      emptyTitle="No receipts waiting"
      subtitle="Card transactions that still need a receipt will land here."
      action="Upload a receipt"
    />
  );
}
