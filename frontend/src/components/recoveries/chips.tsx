"use client";

import { StatusChip } from "@/components/ramp/data-table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const STRENGTH = {
  High: "bg-[#e7f6ea] text-[#1c7a42]",
  Medium: "bg-[#fbf3d0] text-[#8a6a00]",
  Low: "bg-[#f1efe9] text-[#5c5c5c]",
  Tracked: "bg-[#f1efe9] text-[#5c5c5c]",
};

export function StrengthChip({ strength }: { strength: string }) {
  const chip = (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[12px] font-medium",
        STRENGTH[strength as keyof typeof STRENGTH] ?? STRENGTH.Low,
      )}
    >
      {strength}
    </span>
  );
  if (strength !== "Tracked") return chip;
  return (
    <Tooltip>
      <TooltipTrigger
        render={chip}
        className="cursor-default border-0 bg-transparent p-0"
        aria-label="Tracked, not refundable"
      />
      <TooltipContent>Not refundable</TooltipContent>
    </Tooltip>
  );
}

const STATUS_TONE = {
  Drafted: "yellow",
  Sent: "blue",
  Credited: "green",
  Found: "gray",
  "Needs review": "yellow",
} as const;

export function StatusDot({ status }: { status: string }) {
  const tone = STATUS_TONE[status as keyof typeof STATUS_TONE] ?? "gray";
  return <StatusChip label={status} tone={tone} />;
}
