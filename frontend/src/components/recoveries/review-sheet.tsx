"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { PriceChart } from "@/components/recoveries/price-chart";
import { PrimaryButton, SecondaryButton } from "@/components/ramp/buttons";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import {
  approveLetter,
  billDocumentUrl,
  getClaim,
  saveLetter,
  simulateAgree,
  updateImportShare,
  usd,
  type ClaimDetail,
  type EvidenceItem,
  type PriceTest,
  type SkuHistory,
} from "@/lib/recoveries";
import { StrengthChip, StatusDot } from "@/components/recoveries/chips";

function tierOf(labeledBy: string): 1 | 2 | null {
  const value = labeledBy.toLowerCase();
  if (value.endsWith("tier1") || value.includes("haiku")) return 1;
  if (value.endsWith("tier2") || value.includes("sonnet")) return 2;
  return null;
}

export function ReviewSheet({
  vendorId,
  open,
  onOpenChange,
  onStatus,
  onRefundable,
}: {
  vendorId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStatus: (vendorId: string, status: string) => void;
  onRefundable?: (vendorId: string, refundable: number, strength: string | null) => void;
}) {
  const [detail, setDetail] = useState<ClaimDetail | null>(null);
  const [body, setBody] = useState("");
  const [saved, setSaved] = useState("");
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showAllCharts, setShowAllCharts] = useState(false);
  const router = useRouter();

  useEffect(() => {
    if (!open || !vendorId) return;
    let cancelled = false;
    setDetail(null);
    setShowAllCharts(false);
    getClaim(vendorId)
      .then((next) => {
        if (cancelled) return;
        setDetail(next);
        const letter = next.letter?.body ?? "";
        setBody(letter);
        setSaved(letter);
      })
      .catch((error: Error) => toast.error(error.message));
    return () => {
      cancelled = true;
    };
  }, [open, vendorId]);

  useEffect(() => {
    if (!detail?.letter || body === saved) return;
    const timer = window.setTimeout(() => {
      void persist(false);
    }, 700);
    return () => window.clearTimeout(timer);
    // persist reads the latest body via the closure of this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [body, saved, detail?.vendor_id]);

  async function persist(manual: boolean) {
    if (!detail) return false;
    const next = body;
    setSaving(true);
    try {
      await saveLetter(detail.vendor_id, next);
      setSaved(next);
      if (manual) toast.success("Draft saved");
      return true;
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Couldn't save the letter");
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function approve() {
    if (!detail) return;
    setBusy(true);
    try {
      if (body !== saved) {
        const ok = await persist(false);
        if (!ok) return;
      }
      const result = await approveLetter(detail.vendor_id);
      setDetail({ ...detail, status: result.status, letter: detail.letter ? { ...detail.letter, status: "sent" } : null });
      onStatus(detail.vendor_id, result.status);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Couldn't send the letter");
    } finally {
      setBusy(false);
    }
  }

  async function agree() {
    if (!detail) return;
    setBusy(true);
    try {
      const result = await simulateAgree(detail.vendor_id);
      setDetail({ ...detail, status: result.status });
      onStatus(detail.vendor_id, result.status);
      const billId = result.applied_to_bill_id;
      toast.success(`Vendor credit of ${usd(result.amount)} added to Bill Pay`, {
        duration: 12000,
        action: billId
          ? {
              label: "View bill",
              onClick: () => router.push(`/bill-pay/bills/${billId}`),
            }
          : undefined,
      });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "The supplier didn't agree");
    } finally {
      setBusy(false);
    }
  }

  const applyShare = useCallback(
    async (share: number) => {
      if (!detail) return;
      const next = await updateImportShare(detail.vendor_id, share);
      setDetail(next);
      const letter = next.letter?.body ?? "";
      setBody(letter);
      setSaved(letter);
      onRefundable?.(next.vendor_id, next.refundable, next.strength);
    },
    [detail, onRefundable],
  );

  const tier1 = detail?.evidence.filter((item) => tierOf(item.labeled_by) === 1).length ?? 0;
  const tier2 = detail?.evidence.filter((item) => tierOf(item.labeled_by) === 2).length ?? 0;
  const drafted = detail?.status === "Drafted";

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full min-w-0 max-w-[100vw] flex-col gap-0 overflow-hidden p-0 data-[side=right]:!w-[min(100vw,560px)] data-[side=right]:!max-w-[min(100vw,560px)] data-[side=right]:sm:!max-w-[min(100vw,560px)]"
        showCloseButton
      >
        <SheetTitle className="sr-only">{detail?.vendor ?? "Claim"}</SheetTitle>
        {!detail ? (
          <div className="p-6 text-[14px] text-[#6f6c66]">Loading the claim…</div>
        ) : (
          <>
            <div className="border-b border-[#eeeae4] px-6 py-5 pr-12">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-[22px] font-normal tracking-[-0.02em] text-[#1c1c1c]">{detail.vendor}</h2>
                  <p className="mt-1 text-[20px] tabular-nums text-[#1c1c1c]">{usd(detail.refundable)}</p>
                </div>
                <div className="flex items-center gap-2">
                  {detail.evidence_tier ? <TierChip tier={detail.evidence_tier} /> : null}
                  {detail.strength ? <StrengthChip strength={detail.strength} /> : null}
                  <StatusDot status={detail.status} />
                </div>
              </div>
              <ul className="mt-3 list-disc space-y-1 pl-4 text-[13px] text-[#3f3f3f]">
                {reasons(detail).map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
              {detail.status === "Sent" ? (
                <button
                  type="button"
                  onClick={agree}
                  disabled={busy}
                  className="mt-3 text-[13px] text-[#1c1c1c] underline decoration-[#d5d1c8] underline-offset-2"
                >
                  Simulate supplier agrees
                </button>
              ) : null}
            </div>
            <div data-sheet-body className="min-h-0 min-w-0 flex-1 space-y-6 overflow-y-auto overflow-x-hidden px-6 py-5">
              <section className="min-w-0">
                <h3 className="text-[13px] font-medium text-[#1c1c1c]">Why we flagged this</h3>
                {detail.price_history.length > 0 ? (
                  <>
                    <ImportShare
                      share={detail.import_cost_share ?? 0.6}
                      locked={detail.status === "Sent" || detail.status === "Credited"}
                      onCommit={applyShare}
                    />
                    <PriceCharts
                      skus={detail.price_history}
                      raw={detail.raw_price_increase}
                      claimed={detail.conservative_price_increase}
                      low={detail.claim_low}
                      expected={detail.claim_expected}
                      high={detail.claim_high}
                      showAll={showAllCharts}
                      onShowAll={() => setShowAllCharts(true)}
                    />
                  </>
                ) : null}
                <EvidenceGroups items={detail.evidence} />
              </section>

              {detail.contract?.clause_text ? (
                <section>
                  <h3 className="text-[13px] font-medium text-[#1c1c1c]">Contract</h3>
                  <blockquote className="mt-2 border-l-2 border-[#e4f222] bg-[#fafaf8] px-4 py-3">
                    {detail.contract.clause_number ? (
                      <p className="mb-1 text-[12px] font-medium text-[#6f6c66]">Clause {detail.contract.clause_number}</p>
                    ) : null}
                    <p className="text-[13.5px] leading-6 text-[#1c1c1c]">{detail.contract.clause_text}</p>
                  </blockquote>
                </section>
              ) : null}

              {detail.credits_already_received.length > 0 ? (
                <section>
                  <h3 className="text-[13px] font-medium text-[#1c1c1c]">Credits already received</h3>
                  <ul className="mt-2 space-y-2">
                    {detail.credits_already_received.map((credit) => (
                      <li key={credit.credit_memo_number} className="text-[13px] text-[#3f3f3f]">
                        <span className="font-medium text-[#1c1c1c]">{usd(credit.amount)}</span>
                        {" · "}
                        {credit.credit_memo_number}
                        {credit.memo ? ` · ${credit.memo}` : ""}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              <p className="text-[12px] text-[#8a8680]">
                {tier1} lines labeled by tier 1 · {tier2} lines labeled by tier 2
              </p>

              {detail.letter ? (
                <section>
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-[13px] font-medium text-[#1c1c1c]">Letter</h3>
                    <span className="text-[12px] text-[#8a8680]">{saving ? "Saving…" : body === saved ? "Saved" : "Unsaved"}</span>
                  </div>
                  <Textarea
                    value={body}
                    onChange={(event) => setBody(event.target.value)}
                    className="min-h-[280px] rounded-md border-[#e3e1db] text-[13.5px] leading-6 shadow-none focus-visible:ring-0"
                  />
                </section>
              ) : (
                <p className="text-[13px] text-[#6f6c66]">
                  {detail.status === "Needs review"
                    ? "No letter yet. This price increase needs a control group before it can be claimed."
                    : "No letter. Nothing here is refundable from the supplier."}
                </p>
              )}

            </div>
            {detail.letter && (drafted || detail.status === "Found") ? (
              <div className="flex items-center justify-end gap-2 border-t border-[#eeeae4] px-6 py-4">
                <SecondaryButton disabled={saving || busy} onClick={() => persist(true)}>
                  Save draft
                </SecondaryButton>
                {drafted ? (
                  <PrimaryButton disabled={busy || saving} onClick={approve}>
                    Approve and send
                  </PrimaryButton>
                ) : null}
              </div>
            ) : null}
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

function PriceCharts({
  skus,
  raw,
  claimed,
  low,
  expected,
  high,
  showAll,
  onShowAll,
}: {
  skus: SkuHistory[];
  raw: number;
  claimed: number;
  low?: number | null;
  expected?: number | null;
  high?: number | null;
  showAll: boolean;
  onShowAll: () => void;
}) {
  const ranked = [...skus].sort((a, b) => b.conservative_increase - a.conservative_increase);
  const visible = showAll ? ranked : ranked.slice(0, 3);
  const ranged = low != null && expected != null && high != null && (expected ?? 0) > 0;
  const needsReview = skus.some((sku) => sku.tests?.some((test) => test.id === "control" && testStatus(test) === "needs_review"));
  return (
    <div className="mt-3 space-y-3">
      <p className="text-[13px] text-[#3f3f3f]">
        {needsReview && !ranged
          ? "Not claimed. There is no control group, so this price increase needs review."
          : ranged
            ? `Low ${usd(low ?? 0)} (half the pass-through) · Expected ${usd(expected ?? 0)} · High ${usd(high ?? 0)} (raw increase). We claim the expected amount.`
            : `Raw increase ${usd(raw)} · We claim ${usd(claimed)}`}
      </p>
      {visible.map((sku) => (
        <div key={sku.sku}>
          <PriceChart sku={sku} />
          <PriceChecklist sku={sku} />
        </div>
      ))}
      {!showAll && ranked.length > 3 ? (
        <button
          type="button"
          onClick={onShowAll}
          className="text-[13px] text-[#1c1c1c] underline decoration-[#d5d1c8] underline-offset-2"
        >
          Show all {ranked.length}
        </button>
      ) : null}
    </div>
  );
}

function EvidenceGroups({ items }: { items: EvidenceItem[] }) {
  const groups = useMemo(() => groupEvidence(items), [items]);
  const [open, setOpen] = useState<string | null>(groups[0]?.name ?? null);
  return (
    <ul className="mt-4 divide-y divide-[#f1efe9] border-t border-[#f1efe9]">
      {groups.map((group) => {
        const expanded = open === group.name;
        return (
          <li key={group.name}>
            <button
              type="button"
              onClick={() => setOpen(expanded ? null : group.name)}
              className="flex w-full items-start gap-2 py-2.5 text-left"
              aria-expanded={expanded}
            >
              {expanded ? (
                <ChevronDown className="mt-0.5 size-4 shrink-0 text-[#8a8680]" />
              ) : (
                <ChevronRight className="mt-0.5 size-4 shrink-0 text-[#8a8680]" />
              )}
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] text-[#1c1c1c]">{group.name}</span>
                <span className="mt-0.5 block text-[12px] text-[#8a8680]">
                  {group.invoices} {group.invoices === 1 ? "invoice" : "invoices"}
                </span>
              </span>
              <span className="shrink-0 text-[13px] tabular-nums text-[#1c1c1c]">{usd(group.total)}</span>
            </button>
            {expanded ? (
              <ul className="mb-2 ml-6 space-y-1.5">
                {group.lines.map((line) => (
                  <li
                    key={`${line.invoice_number}-${line.line_index}-${line.type}`}
                    className="flex items-baseline justify-between gap-3 text-[12px]"
                  >
                    <span className="min-w-0 text-[#6f6c66]">
                      {line.date}
                      {" · "}
                      {line.bill_id ? (
                        <a
                          href={billDocumentUrl(line.bill_id)}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[#1c1c1c] underline decoration-[#d5d1c8] underline-offset-2 hover:decoration-[#1c1c1c]"
                        >
                          {line.invoice_number}
                        </a>
                      ) : (
                        line.invoice_number
                      )}
                    </span>
                    <span className="shrink-0 tabular-nums text-[#1c1c1c]">{usd(line.amount)}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function groupEvidence(items: EvidenceItem[]) {
  const byName = new Map<string, EvidenceItem[]>();
  for (const item of items) {
    const list = byName.get(item.description) ?? [];
    list.push(item);
    byName.set(item.description, list);
  }
  return [...byName.entries()]
    .map(([name, lines]) => ({
      name,
      invoices: new Set(lines.map((line) => line.invoice_number)).size,
      total: lines.reduce((sum, line) => sum + line.amount, 0),
      lines: [...lines].sort((a, b) => a.date.localeCompare(b.date) || a.invoice_number.localeCompare(b.invoice_number)),
    }))
    .sort((a, b) => b.total - a.total || a.name.localeCompare(b.name));
}

const TIER_LABEL: Record<string, string> = {
  documented: "Documented",
  contract_price: "Contract + price",
  price_only: "Price-only",
};

function TierChip({ tier }: { tier: string }) {
  return (
    <span className="rounded-full bg-[#f4f1ea] px-2 py-0.5 text-[12px] text-[#3f3f3f]">{TIER_LABEL[tier] ?? tier}</span>
  );
}

function ImportShare({
  share,
  locked,
  onCommit,
}: {
  share: number;
  locked: boolean;
  onCommit: (share: number) => Promise<void>;
}) {
  const [percent, setPercent] = useState(String(Math.round(share * 100)));
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setPercent(String(Math.round(share * 100)));
  }, [share]);
  useEffect(() => {
    if (locked) return;
    const next = Number(percent);
    if (!Number.isInteger(next) || next < 1 || next > 100) return;
    const asShare = next / 100;
    if (Math.abs(asShare - share) < 0.001) return;
    const timer = window.setTimeout(() => {
      setSaving(true);
      onCommit(asShare)
        .catch((error: Error) => toast.error(error.message))
        .finally(() => setSaving(false));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [percent, share, locked, onCommit]);
  return (
    <div className="mt-3">
      <label className="flex flex-wrap items-center gap-2 text-[13px] text-[#1c1c1c]" htmlFor="import-cost-share">
        Assumes import cost is about
        <Input
          id="import-cost-share"
          type="number"
          min={1}
          max={100}
          step={1}
          inputMode="numeric"
          disabled={locked || saving}
          value={percent}
          onChange={(event) => setPercent(event.target.value)}
          className="h-8 w-16 rounded-md border-[#e3e1db] px-2 text-center text-[13px] shadow-none"
          aria-label="Import cost as a percent of price"
        />
        % of price.
      </label>
      <p className="mt-1 text-[12px] text-[#6f6c66]">
        {saving ? "Recalculating the claim…" : "Changing this recalculates which price increases still fit under the tariff."}
        {locked ? " This claim was already sent." : ""}
      </p>
    </div>
  );
}

function testStatus(test: PriceTest) {
  return test.status ?? (test.passed ? "pass" : "fail");
}

function PriceChecklist({ sku }: { sku: SkuHistory }) {
  if (!sku.tests?.length) return null;
  const origin = sku.origin_inferred ? "Origin inferred" : sku.country || "Origin not stated";
  const hts = sku.hts_chapter ? `HTS ch. ${sku.hts_chapter}` : null;
  return (
    <div className="mt-2 mb-1">
      <p className="text-[12px] text-[#6f6c66]">
        {origin}
        {hts ? ` · ${hts}` : ""}
      </p>
      <ul className="mt-1 space-y-1">
        {sku.tests.map((test) => {
          const status = testStatus(test);
          const label = status === "needs_review" ? "Needs review" : status === "pass" ? "Pass" : "Fail";
          const tone =
            status === "pass" ? "text-[#1f8a4c]" : status === "needs_review" ? "text-[#8a6a00]" : "text-[#9a3412]";
          return (
            <li key={test.id} className="text-[12px] leading-5 text-[#3f3f3f]">
              <span className={tone}>{label}</span>
              {" · "}
              {test.name}
              {test.required ? "" : " (not required)"}
              <span className="block text-[#6f6c66]">{test.detail}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function reasons(detail: ClaimDetail) {
  if (detail.tier_reasons && detail.tier_reasons.length > 0) return detail.tier_reasons;
  const lines: string[] = [];
  const surcharge = detail.evidence.some((item) => item.type === "tariff_ieepa_surcharge");
  const price = detail.evidence.some((item) => item.type === "price_excess");
  if (surcharge) lines.push("An explicit IEEPA surcharge is on the invoice.");
  if (price && detail.price_reverted === true) lines.push("The price increase reverted after the tariff window.");
  if (price && detail.price_reverted === false) lines.push("The price increase did not revert after the window.");
  if (price && detail.price_reverted == null) lines.push("No later invoice confirmed that the price came back down.");
  if (detail.contract?.refund_or_credit_clause) {
    lines.push(
      detail.contract.clause_number
        ? `Clause ${detail.contract.clause_number} requires a credit if the tariff is refunded.`
        : "The contract requires a credit if the tariff is refunded.",
    );
  }
  if (detail.strength === "Tracked") lines.push("Section 301 charges are tracked, not claimed from the supplier.");
  if (detail.strength === "Low" && !lines.length) lines.push("The only evidence is a price increase.");
  if (!lines.length) lines.push(detail.subtitle || "Flagged from the paid bills.");
  return lines;
}
