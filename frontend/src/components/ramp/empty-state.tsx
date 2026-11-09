import type { ReactNode } from "react";
import { SecondaryButton } from "@/components/ramp/buttons";

export function EmptyState({
  title,
  subtitle,
  action,
  onAction,
  footnote,
}: {
  title: string;
  subtitle: string;
  action?: string;
  onAction?: () => void;
  footnote?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 text-center">
      <h2 className="text-[16px] font-semibold tracking-[-0.01em] text-[#1c1c1c]">{title}</h2>
      <p className="mt-2 max-w-md text-[14px] leading-6 text-[#6f6c66]">{subtitle}</p>
      {action ? (
        <SecondaryButton className="mt-6" onClick={onAction}>
          {action}
        </SecondaryButton>
      ) : null}
      {footnote ? <div className="mt-8 text-[13px] text-[#6f6c66]">{footnote}</div> : null}
    </div>
  );
}
