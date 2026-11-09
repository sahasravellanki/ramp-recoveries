"use client";

import { PlaceholderPage } from "@/components/ramp/placeholder-page";

export default function RecoveriesPage() {
  return (
    <PlaceholderPage
      title="Recoveries"
      breadcrumb={{ label: "Bill Pay", href: "/bill-pay/bills" }}
      emptyTitle="No claims on this screen yet"
      subtitle="A scan of paid bills will list the suppliers who may owe tariff refunds, with a letter ready for review."
      action="Back to bills"
      actionHref="/bill-pay/bills"
    />
  );
}
