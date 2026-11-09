"use client";

import { X } from "lucide-react";
import { useState } from "react";
import { SecondaryButton } from "@/components/ramp/buttons";
import { cn } from "@/lib/utils";

export function NoticeBanner({
  tone,
  title,
  detail,
  action,
  onAction,
}: {
  tone: "green" | "yellow";
  title: string;
  detail: string;
  action: string;
  onAction?: () => void;
}) {
  const [open, setOpen] = useState(true);
  if (!open) return null;

  return (
    <div
      className={cn(
        "flex items-center gap-4 rounded-md border px-4 py-3",
        tone === "green" && "border-[#c5e3bf] bg-[#f2faef]",
        tone === "yellow" && "border-[#ead48a] bg-[#fbf6df]",
      )}
    >
      <div className="min-w-0 flex-1">
        <p className="text-[14px] font-medium leading-5 text-[#1c1c1c]">{title}</p>
        <p className="text-[13px] leading-5 text-[#5d645c]">{detail}</p>
      </div>
      <SecondaryButton className="shrink-0 bg-white" onClick={onAction}>
        {action}
      </SecondaryButton>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => setOpen(false)}
        className="grid size-7 shrink-0 place-items-center rounded-md text-[#5c5c5c] hover:bg-black/5"
      >
        <X className="size-4" />
      </button>
    </div>
  );
}
