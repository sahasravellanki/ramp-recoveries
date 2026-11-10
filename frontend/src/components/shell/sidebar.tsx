"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { PanelLeft, Sparkles } from "lucide-react";
import { Mark } from "@/components/ramp/mark";
import { MAIN_NAV, SECONDARY_NAV, childIsActive, sectionIsActive, type NavItem } from "@/lib/nav";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export function Sidebar({
  collapsed = false,
  onToggle,
  onNavigate,
}: {
  collapsed?: boolean;
  onToggle?: () => void;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "flex h-full shrink-0 flex-col border-r border-[#e7e5e0] bg-[#f4f3f0] text-[#2c2c2c]",
        collapsed ? "w-[68px]" : "w-[220px]",
      )}
    >
      <div className={cn("flex items-center gap-1 pt-3.5 pb-1", collapsed ? "justify-center px-2" : "px-3")}>
        {collapsed ? (
          <Mark className="size-5" />
        ) : (
          <div className="flex h-8 min-w-0 flex-1 items-center rounded-full border border-[#e4e2dc] bg-white p-0.5">
            <span className="flex h-full items-center gap-1.5 rounded-full bg-[#f3f2ee] px-2 text-[13px] font-medium text-[#1c1c1c]">
              <Mark className="size-3.5" />
              Ramp
            </span>
            <button
              type="button"
              className="px-2.5 text-[13px] text-[#6a6761] hover:text-[#1c1c1c]"
              onClick={() => toast("Stack isn't connected in this prototype.")}
            >
              Stack
            </button>
          </div>
        )}
        {onToggle ? (
          <button
            type="button"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={onToggle}
            className="grid size-8 shrink-0 place-items-center rounded-md text-[#6d6a64] hover:bg-[#eae8e3]"
          >
            <PanelLeft className="size-4" strokeWidth={1.75} />
          </button>
        ) : null}
      </div>
      {collapsed ? null : (
        <div className="px-4 pt-1 pb-2">
          <p className="text-[12px] text-[#9c978f]">Prototype</p>
          <p className="mt-1 text-[11px] leading-4 text-[#9c978f]">
            Hackathon project.
            <br />
            Not affiliated with Ramp.
          </p>
        </div>
      )}

      <nav className="flex-1 overflow-y-auto px-2 pb-3">
        <NavList items={MAIN_NAV} pathname={pathname} collapsed={collapsed} onNavigate={onNavigate} />
        <div className="mx-2 my-2 h-px bg-[#e4e1db]" />
        <NavList items={SECONDARY_NAV} pathname={pathname} collapsed={collapsed} onNavigate={onNavigate} />
      </nav>

      <div className="px-2 pb-3">
        <Link
          href="/#ask"
          onClick={onNavigate}
          className={cn(
            "flex h-9 items-center gap-2.5 rounded-md px-2 text-[13.5px] text-[#2c2c2c] hover:bg-[#eae8e3]",
            collapsed && "justify-center px-0",
          )}
        >
          <Sparkles className="size-4 shrink-0" strokeWidth={1.75} />
          {collapsed ? <span className="sr-only">Ask Ramp</span> : "Ask Ramp"}
        </Link>
      </div>
    </aside>
  );
}

function NavList({
  items,
  pathname,
  collapsed,
  onNavigate,
}: {
  items: NavItem[];
  pathname: string;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  return (
    <ul className="space-y-0.5">
      {items.map((item) => {
        const active = sectionIsActive(item, pathname);
        const Icon = item.icon;
        const children = item.children;
        if (active && children && !collapsed) {
          return (
            <li key={item.label}>
              <div className="rounded-lg bg-[#e8e6e2] p-1">
                <Link
                  href={item.href}
                  onClick={onNavigate}
                  className="flex h-8 items-center gap-2.5 rounded-md px-2 text-[13.5px] font-medium text-[#1c1c1c]"
                >
                  <Icon className="size-4" strokeWidth={1.75} />
                  {item.label}
                </Link>
                <ul className="mt-0.5 space-y-0.5 pb-0.5 pl-7">
                  {children.map((child) => {
                    const childActive = childIsActive(child, children, pathname);
                    return (
                      <li key={child.label}>
                        <Link
                          href={child.href}
                          onClick={onNavigate}
                          className={cn(
                            "flex h-8 items-center gap-2 rounded-md px-2 text-[13.5px]",
                            childActive
                              ? "bg-white font-medium text-[#1c1c1c] shadow-[0_1px_1px_rgba(0,0,0,0.04)]"
                              : "text-[#3a3a3a] hover:bg-white/60",
                          )}
                        >
                          <span className="truncate">{child.label}</span>
                          {child.badge ? (
                            <span className="ml-auto rounded-full bg-[#e4f222] px-1.5 py-[2px] text-[10px] leading-none font-semibold text-[#1c1c1c]">
                              {child.badge}
                            </span>
                          ) : null}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            </li>
          );
        }

        return (
          <li key={item.label}>
            <Link
              href={item.href}
              title={collapsed ? item.label : undefined}
              onClick={onNavigate}
              className={cn(
                "flex h-8 items-center gap-2.5 rounded-md px-2 text-[13.5px] text-[#2f2f2f] hover:bg-[#eae8e3]",
                collapsed && "justify-center px-0",
                active && "bg-[#e8e6e2] font-medium text-[#1c1c1c]",
              )}
            >
              <Icon className="size-4 shrink-0" strokeWidth={1.75} />
              {collapsed ? <span className="sr-only">{item.label}</span> : item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
