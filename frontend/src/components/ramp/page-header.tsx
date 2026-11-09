import Link from "next/link";
import type { ReactNode } from "react";

export function PageHeader({
  title,
  breadcrumb,
  actions,
}: {
  title: string;
  breadcrumb?: { label: string; href: string };
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        {breadcrumb ? (
          <Link
            href={breadcrumb.href}
            className="mb-1 block text-[13px] text-[#8a8680] hover:text-[#1c1c1c]"
          >
            {breadcrumb.label}
          </Link>
        ) : null}
        <h1 className="text-[44px] font-normal leading-none tracking-[-0.03em] text-[#161616]">
          {title}
        </h1>
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}
