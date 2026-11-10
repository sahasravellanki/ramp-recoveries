import type { ComponentProps, ReactNode } from "react";
import { MoreHorizontal } from "lucide-react";
import { SecondaryButton } from "@/components/ramp/buttons";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

export type Column<T> = {
  key: string;
  header: string;
  align?: "left" | "right";
  width?: string;
  render: (row: T) => ReactNode;
};

export function VendorCell({
  name,
  subtitle,
  initials,
}: {
  name: string;
  subtitle?: string;
  initials: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="grid size-8 shrink-0 place-items-center rounded-full bg-[#eceae4] text-[11px] font-medium text-[#3c3c3c]">
        {initials}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-[14px] text-[#1c1c1c]">{name}</span>
        {subtitle ? <span className="block truncate text-[12px] text-[#8a8680]">{subtitle}</span> : null}
      </span>
    </div>
  );
}

const DOT = {
  green: "bg-[#1f8a4c]",
  yellow: "bg-[#c4a000]",
  gray: "bg-[#9a9a9a]",
  blue: "bg-[#3b6fd8]",
  red: "bg-[#c44848]",
};

export function StatusChip({
  label,
  tone,
}: {
  label: string;
  tone: keyof typeof DOT;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px] text-[#1c1c1c]">
      <span className={cn("size-1.5 rounded-full", DOT[tone])} />
      {label}
    </span>
  );
}

export function Money({ amount }: { amount: string }) {
  return (
    <span className="tabular-nums text-[14px] text-[#1c1c1c]">
      {amount} <span className="text-[#8a8680]">USD</span>
    </span>
  );
}

export function RowActions({ onReview, onOpen }: { onReview?: () => void; onOpen?: () => void }) {
  return (
    <div className="flex items-center justify-end gap-2">
      <SecondaryButton className="h-8 px-3" onClick={onReview}>
        Review
      </SecondaryButton>
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label="More actions"
          className="grid size-8 place-items-center rounded-md text-[#5c5c5c] hover:bg-[#f4f3f1]"
        >
          <MoreHorizontal className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={onOpen ?? onReview}>Open</DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => {
              const url = window.location.href;
              void navigator.clipboard?.writeText(url);
            }}
          >
            Copy link
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  footer,
  empty,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  footer?: string;
  empty?: ReactNode;
}) {
  if (rows.length === 0 && empty) {
    return <div className="flex flex-1 items-center justify-center py-16">{empty}</div>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse text-left">
        <thead>
          <tr className="border-b border-[#eeeae4]">
            {columns.map((column) => (
              <th
                key={column.key}
                className={cn(
                  "h-10 px-3 text-[12px] font-medium text-[#8a8680]",
                  column.align === "right" && "text-right",
                )}
                style={{ width: column.width }}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className="h-[60px] border-b border-[#f1efe9] hover:bg-[#fafaf8]">
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={cn("px-3", column.align === "right" && "text-right")}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {footer ? <p className="px-3 py-4 text-[13px] text-[#6f6c66]">{footer}</p> : null}
    </div>
  );
}

export function QuietLinkButton({ children, ...props }: ComponentProps<typeof Button>) {
  return (
    <Button variant="link" className="h-auto p-0 text-[13px] text-[#1c1c1c] underline" {...props}>
      {children}
    </Button>
  );
}
