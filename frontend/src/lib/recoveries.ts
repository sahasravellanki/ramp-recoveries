import { API_URL } from "@/lib/api";

export type ClaimCard = {
  vendor_id: string;
  vendor: string;
  refundable: number;
  strength: string | null;
  status: string;
  bill_count: number;
  subtitle: string;
};

export type ImporterCase = {
  invoice_number: string;
  vendor: string;
  vendor_id?: string | null;
  issued_at: string;
  description: string;
  amount: number;
  note: string;
  guidance?: string;
};

export type RecoveriesSummary = {
  net_refundable: number;
  non_refundable: number;
  needs_review_count: number;
  importer_of_record: { count: number; total: number; cases: ImporterCase[] };
  credits_already_received: number;
  claims: ClaimCard[];
};

export type ScanStatus = {
  scan_id: string;
  status: string;
  step: string;
  step_index: number;
  step_count: number;
  steps: string[];
  cached: boolean;
  error: string | null;
};

export type EvidenceItem = {
  invoice_number: string;
  line_index: number;
  date: string;
  description: string;
  amount: number;
  type: string;
  labeled_by: string;
  bill_id: string | null;
};

export type PricePoint = {
  period: "before" | "during" | "after";
  date: string;
  unit_price: number;
  invoice_number: string;
  expected_price: number | null;
};

export type SkuHistory = {
  sku: string;
  description: string;
  baseline: number;
  expected_price: number;
  benchmark_price: number | null;
  benchmark_is_mock: boolean;
  fell_back: boolean | null;
  raw_increase: number;
  conservative_increase: number;
  points: PricePoint[];
};

export type ClaimDetail = {
  vendor_id: string;
  vendor: string;
  contact_email: string | null;
  strength: string | null;
  status: string;
  subtitle: string;
  bill_count: number;
  refundable: number;
  non_refundable: number;
  raw_price_increase: number;
  conservative_price_increase: number;
  price_reverted: boolean | null;
  evidence: EvidenceItem[];
  price_history: SkuHistory[];
  contract: {
    mentions_tariffs: boolean;
    refund_or_credit_clause: boolean;
    clause_number: string | null;
    clause_text: string | null;
    summary: string | null;
  };
  credits_already_received: { credit_memo_number: string; amount: number; memo: string | null; issued_at: string }[];
  letter: { body: string; status: string; word_count: number; edited: boolean } | null;
};

async function read<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

export function getRecoveries() {
  return read<RecoveriesSummary>("/api/recoveries");
}

export function getClaim(vendorId: string) {
  return read<ClaimDetail>(`/api/recoveries/${vendorId}`);
}

export function startScan() {
  return read<{ scan_id: string; status: string }>("/api/recoveries/scan", { method: "POST" });
}

export function getScan(scanId: string) {
  return read<ScanStatus>(`/api/recoveries/scan/${scanId}`);
}

export function saveLetter(vendorId: string, body: string) {
  return read<{ body: string; word_count: number; edited: boolean }>(`/api/recoveries/${vendorId}/letter`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });
}

export function approveLetter(vendorId: string) {
  return read<{ status: string }>(`/api/recoveries/${vendorId}/approve`, { method: "POST" });
}

export function simulateAgree(vendorId: string) {
  return read<{ status: string; amount: number; applied_to_bill_id: string | null }>(
    `/api/recoveries/${vendorId}/simulate-agree`,
    { method: "POST" },
  );
}

export async function uploadPdfs(files: File[]) {
  const body = new FormData();
  for (const file of files) body.append("files", file);
  return read<{ scan_id: string; created: { invoice_number: string }[]; skipped: string[] }>("/api/uploads", {
    method: "POST",
    body,
  });
}

export function billDocumentUrl(billId: string) {
  return `${API_URL}/api/bills/${billId}/document`;
}

export function usd(value: number) {
  return value.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function initials(name: string) {
  const words = name
    .replace(/&/g, " ")
    .split(/\s+/)
    .filter((word) => /^[A-Za-z]/.test(word));
  return ((words[0]?.[0] ?? "") + (words[1]?.[0] ?? "")).toUpperCase();
}
