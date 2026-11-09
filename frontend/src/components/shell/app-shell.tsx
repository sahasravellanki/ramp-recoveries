"use client";

import { Suspense, useState, type ReactNode } from "react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Sidebar } from "@/components/shell/sidebar";
import { TopBar } from "@/components/shell/topbar";

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden bg-white">
      <div className="hidden h-full md:flex">
        <Suspense fallback={<div className="h-full w-[220px] bg-[#f4f3f0]" />}>
          <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
        </Suspense>
      </div>
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent side="left" className="w-[220px] gap-0 p-0 sm:max-w-[220px]" showCloseButton={false}>
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <Suspense fallback={null}>
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </Suspense>
        </SheetContent>
      </Sheet>
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenu={() => setMobileOpen(true)} />
        <main className="min-h-0 flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
