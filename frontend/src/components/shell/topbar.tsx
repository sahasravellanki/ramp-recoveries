"use client";

import type { ReactNode } from "react";
import { Bell, CircleHelp, Menu, Plus } from "lucide-react";
import { toast } from "sonner";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { resetDemo } from "@/lib/api";
import { DEMO_USER } from "@/lib/nav";

export function TopBar({ onMenu }: { onMenu?: () => void }) {
  async function onReset() {
    try {
      await resetDemo();
      window.dispatchEvent(new Event("demo-reset"));
      toast.success("Reset. Recoveries is back where it started.");
    } catch {
      toast.error("Couldn't reset. Is the API running?");
    }
  }

  return (
    <header className="flex h-14 shrink-0 items-center justify-end gap-1 px-4">
      {onMenu ? (
        <button
          type="button"
          aria-label="Open navigation"
          onClick={onMenu}
          className="mr-auto grid size-9 place-items-center rounded-md text-[#1c1c1c] hover:bg-[#f4f3f1] md:hidden"
        >
          <Menu className="size-[18px]" strokeWidth={1.75} />
        </button>
      ) : null}
      <IconButton label="Notifications" onClick={() => toast("No new notifications.")}>
        <Bell className="size-[18px]" strokeWidth={1.75} />
      </IconButton>
      <IconButton label="Create" onClick={() => toast("Creating records isn't part of this prototype.")}>
        <Plus className="size-[18px]" strokeWidth={1.75} />
      </IconButton>
      <IconButton label="Help" onClick={() => toast("Ask from the box on Home.")}>
        <CircleHelp className="size-[18px]" strokeWidth={1.75} />
      </IconButton>
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label="Account menu"
          className="ml-1 grid size-8 place-items-center rounded-full bg-[#8d897f] text-[12px] font-medium text-white outline-none"
        >
          {DEMO_USER.initials}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-60">
          <DropdownMenuGroup>
            <DropdownMenuLabel className="font-normal">
              <span className="block text-[13px] font-medium text-[#1c1c1c]">{DEMO_USER.company}</span>
              <span className="block text-[12px] text-[#6f6c66]">{DEMO_USER.email}</span>
            </DropdownMenuLabel>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={onReset}>Reset</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="grid size-9 place-items-center rounded-md text-[#1c1c1c] hover:bg-[#f4f3f1]"
    >
      {children}
    </button>
  );
}
