import { Suspense } from "react";
import { BillView } from "./bill-view";

export default function BillPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<p className="px-6 pt-6 text-[14px] text-[#6f6c66] lg:px-8">Loading the bill…</p>}>
      <BillGate params={params} />
    </Suspense>
  );
}

async function BillGate({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <BillView id={id} />;
}
