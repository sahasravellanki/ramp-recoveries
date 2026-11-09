"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { SecondaryButton } from "@/components/ramp/buttons";
import { EmptyState } from "@/components/ramp/empty-state";
import { PageHeader } from "@/components/ramp/page-header";

export function PlaceholderPage({
  title,
  breadcrumb,
  emptyTitle,
  subtitle,
  action,
  actionHref,
  actions,
}: {
  title: string;
  breadcrumb?: { label: string; href: string };
  emptyTitle: string;
  subtitle: string;
  action: string;
  actionHref?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex min-h-full flex-col px-8 pt-1 pb-12">
      <PageHeader title={title} breadcrumb={breadcrumb} actions={actions} />
      <div className="flex flex-1 items-center justify-center py-24">
        <EmptyState
          title={emptyTitle}
          subtitle={subtitle}
          action={actionHref ? undefined : action}
          onAction={() => toast(`${action} isn't part of this prototype.`)}
          footnote={
            actionHref ? (
              <SecondaryButton render={<Link href={actionHref} />}>{action}</SecondaryButton>
            ) : null
          }
        />
      </div>
    </div>
  );
}
