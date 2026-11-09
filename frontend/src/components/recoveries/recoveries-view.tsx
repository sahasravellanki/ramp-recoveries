"use client";

import { Check, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ReviewSheet } from "@/components/recoveries/review-sheet";
import { StatusDot, StrengthChip } from "@/components/recoveries/chips";
import { NoticeBanner } from "@/components/ramp/notice-banner";
import { PageHeader } from "@/components/ramp/page-header";
import { PrimaryButton, SecondaryButton } from "@/components/ramp/buttons";
import { DataTable, Money, RowActions, VendorCell, type Column } from "@/components/ramp/data-table";
import { SearchToolbar } from "@/components/ramp/search-toolbar";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  getRecoveries,
  getScan,
  initials,
  startScan,
  uploadPdfs,
  usd,
  type ClaimCard,
  type RecoveriesSummary,
  type ScanStatus,
} from "@/lib/recoveries";

type TabId = "all" | "review" | "sent" | "credited";

export function RecoveriesView() {
  const [summary, setSummary] = useState<RecoveriesSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [scan, setScan] = useState<ScanStatus | null>(null);
  const [scanning, setScanning] = useState(false);
  const [tab, setTab] = useState<TabId>("all");
  const [query, setQuery] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [shipmentsOpen, setShipmentsOpen] = useState(false);
  const [reviewId, setReviewId] = useState<string | null>(null);

  async function load() {
    const next = await getRecoveries();
    setSummary(next);
    setLoading(false);
  }

  useEffect(() => {
    load().catch((error: Error) => {
      setLoading(false);
      toast.error(error.message);
    });
    const onReset = () => {
      setScan(null);
      setScanning(false);
      setReviewId(null);
      load().catch(() => undefined);
    };
    window.addEventListener("demo-reset", onReset);
    return () => window.removeEventListener("demo-reset", onReset);
  }, []);

  async function watch(scanId: string) {
    setScanning(true);
    try {
      for (;;) {
        const status = await getScan(scanId);
        setScan(status);
        if (status.status === "complete") {
          await load();
          setScanning(false);
          return;
        }
        if (status.status === "error") {
          setScanning(false);
          toast.error(status.error || "The scan failed");
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 300));
      }
    } catch (error) {
      setScanning(false);
      toast.error(error instanceof Error ? error.message : "The scan failed");
    }
  }

  async function scanBills() {
    if (scanning) return;
    try {
      const started = await startScan();
      setScan(placeholderScan(started.scan_id));
      await watch(started.scan_id);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Couldn't start the scan");
    }
  }

  async function upload() {
    if (!files.length) return;
    setUploading(true);
    try {
      const result = await uploadPdfs(files);
      setUploadOpen(false);
      setFiles([]);
      toast.success(
        result.created.length
          ? `Added ${result.created.length} bill${result.created.length === 1 ? "" : "s"}`
          : "Those invoices are already on file",
      );
      await watch(result.scan_id);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  function setStatus(vendorId: string, status: string) {
    setSummary((current) =>
      current
        ? { ...current, claims: current.claims.map((claim) => (claim.vendor_id === vendorId ? { ...claim, status } : claim)) }
        : current,
    );
    load().catch(() => undefined);
  }

  function setRefundable(vendorId: string, refundable: number, strength: string | null) {
    setSummary((current) => {
      if (!current) return current;
      const claims = current.claims.map((claim) =>
        claim.vendor_id === vendorId ? { ...claim, refundable, strength } : claim,
      );
      return {
        ...current,
        claims,
        net_refundable: claims.reduce((sum, claim) => sum + claim.refundable, 0),
      };
    });
  }

  const claims = summary?.claims ?? [];
  const counts = {
    all: claims.length,
    review: claims.filter((claim) => claim.status === "Drafted" || claim.status === "Found" || claim.status === "Needs review").length,
    sent: claims.filter((claim) => claim.status === "Sent").length,
    credited: claims.filter((claim) => claim.status === "Credited").length,
  };
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return claims.filter((claim) => {
      if (tab === "review" && claim.status !== "Drafted" && claim.status !== "Found" && claim.status !== "Needs review") return false;
      if (tab === "sent" && claim.status !== "Sent") return false;
      if (tab === "credited" && claim.status !== "Credited") return false;
      if (!needle) return true;
      return `${claim.vendor} ${claim.subtitle}`.toLowerCase().includes(needle);
    });
  }, [claims, query, tab]);
  const total = visible.reduce((sum, claim) => sum + claim.refundable, 0);
  const cases = summary?.importer_of_record.cases ?? [];
  const showEmpty = !loading && !scanning && claims.length === 0;

  const columns: Column<ClaimCard>[] = [
    {
      key: "vendor",
      header: "Vendor",
      render: (claim) => <VendorCell name={claim.vendor} subtitle={claim.subtitle} initials={initials(claim.vendor)} />,
    },
    {
      key: "refundable",
      header: "Refundable",
      align: "right",
      render: (claim) => <Money amount={usd(claim.refundable).replace("$", "")} />,
    },
    {
      key: "strength",
      header: "Strength",
      render: (claim) => (claim.strength ? <StrengthChip strength={claim.strength} /> : null),
    },
    {
      key: "status",
      header: "Status",
      render: (claim) => <StatusDot status={claim.status} />,
    },
    {
      key: "bills",
      header: "Bills",
      align: "right",
      render: (claim) => <span className="text-[14px] tabular-nums text-[#1c1c1c]">{claim.bill_count}</span>,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (claim) => <RowActions onReview={() => setReviewId(claim.vendor_id)} />,
    },
  ];

  return (
    <TooltipProvider>
      <div className="flex min-h-full w-full min-w-0 flex-col px-6 pt-1 pb-10 lg:px-8">
        <PageHeader
          title="Recoveries"
          subtitle="Tariff costs suppliers may owe you"
          breadcrumb={{ label: "Bill Pay", href: "/bill-pay/bills" }}
          actions={
            <>
              <SecondaryButton onClick={() => setUploadOpen(true)}>Add source</SecondaryButton>
              <PrimaryButton onClick={scanBills} disabled={scanning}>
                {scanning ? "Scanning…" : "Scan bills"}
              </PrimaryButton>
            </>
          }
        />

        {scanning && scan ? <ProgressCard scan={scan} /> : null}

        {showEmpty ? (
          <div className="flex flex-1 flex-col items-center justify-center px-6 py-24 text-center">
            <p className="max-w-md text-[14px] leading-6 text-[#6f6c66]">
              Scan paid bills for IEEPA tariff pass-throughs a supplier may owe back.
            </p>
            <PrimaryButton className="mt-6" onClick={scanBills}>
              Scan bills
            </PrimaryButton>
          </div>
        ) : null}

        {summary && claims.length > 0 && !scanning ? (
          <div className="mt-6 space-y-5">
            <div className="grid w-full grid-cols-2 gap-3 min-[1100px]:grid-cols-4">
              <Stat label="Refundable" value={usd(summary.net_refundable)} />
              <Stat label="Not refundable" value={usd(summary.non_refundable)} />
              <Stat label="Needs review" value={String(counts.review)} />
              <Stat label="Credits received" value={usd(summary.credits_already_received)} />
            </div>

            {cases.length > 0 ? (
              <NoticeBanner
                tone="yellow"
                title={`${cases.length} shipment${cases.length === 1 ? "" : "s"} show you paid customs duty directly`}
                detail={`You're the importer of record for these, so request the ${usd(summary.importer_of_record.total)} refund from CBP instead of a supplier.`}
                action="View shipments"
                onAction={() => setShipmentsOpen(true)}
              />
            ) : null}

            <Tabs value={tab} onValueChange={(value) => setTab(value as TabId)}>
              <TabsList variant="line" className="h-auto gap-1 bg-transparent p-0">
                <TabButton value="all" label="All" count={counts.all} />
                <TabButton value="review" label="To review" count={counts.review} />
                <TabButton value="sent" label="Sent" count={counts.sent} />
                <TabButton value="credited" label="Credited" count={counts.credited} />
              </TabsList>
            </Tabs>

            <SearchToolbar value={query} onChange={setQuery} />

            <DataTable
              columns={columns}
              rows={visible}
              rowKey={(claim) => claim.vendor_id}
              footer={
                visible.length
                  ? `${visible.length === 0 ? 0 : 1}-${visible.length} of ${visible.length} · ${usd(total)} total`
                  : undefined
              }
              empty={
                <p className="text-[14px] text-[#6f6c66]">Nothing in this view. Try another tab or clear the search.</p>
              }
            />
          </div>
        ) : null}

        {loading ? <p className="mt-10 text-[14px] text-[#6f6c66]">Loading claims…</p> : null}
      </div>

      <Dialog open={uploadOpen} onOpenChange={setUploadOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add source</DialogTitle>
            <DialogDescription>Upload invoice PDFs. They are read and included in a new scan.</DialogDescription>
          </DialogHeader>
          <input
            type="file"
            accept="application/pdf"
            multiple
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            className="text-[13px] text-[#3f3f3f] file:mr-3 file:rounded-md file:border file:border-[#dcdad4] file:bg-white file:px-3 file:py-1.5 file:text-[13px]"
          />
          <DialogFooter className="bg-transparent">
            <SecondaryButton onClick={() => setUploadOpen(false)}>Cancel</SecondaryButton>
            <PrimaryButton disabled={!files.length || uploading} onClick={upload}>
              {uploading ? "Uploading…" : "Upload"}
            </PrimaryButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Sheet open={shipmentsOpen} onOpenChange={setShipmentsOpen}>
        <SheetContent side="right" className="w-full sm:max-w-md">
          <SheetHeader>
            <SheetTitle>Importer of record</SheetTitle>
          </SheetHeader>
          <ul className="space-y-4 px-4">
            {cases.map((item) => (
              <li key={item.invoice_number} className="border-b border-[#f1efe9] pb-3">
                <p className="text-[14px] font-medium text-[#1c1c1c]">{item.vendor}</p>
                <p className="mt-0.5 text-[13px] text-[#6f6c66]">
                  {item.invoice_number} · {item.issued_at}
                </p>
                <p className="mt-1 text-[14px] tabular-nums">{usd(item.amount)}</p>
                <p className="mt-1 text-[12px] text-[#6f6c66]">{item.note}</p>
              </li>
            ))}
          </ul>
        </SheetContent>
      </Sheet>

      <ReviewSheet
        vendorId={reviewId}
        open={reviewId != null}
        onOpenChange={(open) => {
          if (!open) setReviewId(null);
        }}
        onStatus={setStatus}
        onRefundable={setRefundable}
      />
    </TooltipProvider>
  );
}

function TabButton({ value, label, count }: { value: string; label: string; count: number }) {
  return (
    <TabsTrigger value={value} className="h-9 flex-none rounded-none px-3 text-[13.5px]">
      {label}
      <span className="text-[12px] text-[#8a8680]">{count}</span>
    </TabsTrigger>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-[#eeeae4] bg-white px-4 py-3">
      <p className="text-[12px] text-[#8a8680]">{label}</p>
      <p className="mt-1 text-[22px] font-normal tracking-[-0.02em] text-[#1c1c1c] tabular-nums">{value}</p>
    </div>
  );
}

function ProgressCard({ scan }: { scan: ScanStatus }) {
  return (
    <div className="mt-6 rounded-lg border border-[#e6e4df] bg-white p-5">
      <p className="text-[15px] font-medium text-[#1c1c1c]">Scanning paid bills</p>
      <ol className="mt-4 space-y-2.5">
        {scan.steps.map((step, index) => {
          const done = scan.status === "complete" || index + 1 < scan.step_index;
          const active = scan.status === "running" && index + 1 === scan.step_index;
          return (
            <li
              key={step}
              data-state={done ? "done" : active ? "active" : "pending"}
              className="flex items-center gap-2.5 text-[13.5px] text-[#1c1c1c]"
            >
              {done ? (
                <span className="grid size-5 place-items-center rounded-full bg-[#e7f6ea] text-[#1c7a42]">
                  <Check className="size-3" />
                </span>
              ) : active ? (
                <Loader2 className="size-5 animate-spin text-[#1c1c1c]" />
              ) : (
                <span className="size-5 rounded-full border border-[#e1dfda]" />
              )}
              <span className={done || active ? "" : "text-[#8a8680]"}>{capitalize(step)}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

const SCAN_STEPS = [
  "reading bills",
  "labeling lines",
  "checking prices",
  "reviewing contracts",
  "building claims",
  "drafting letters",
];

function placeholderScan(scanId: string): ScanStatus {
  return {
    scan_id: scanId,
    status: "running",
    step: SCAN_STEPS[0],
    step_index: 1,
    step_count: SCAN_STEPS.length,
    steps: SCAN_STEPS,
    cached: false,
    error: null,
  };
}
