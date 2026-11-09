import type { ReactNode } from "react";
import { Input } from "@/components/ui/input";
import { IconButton } from "@/components/ramp/buttons";
import { ListFilter, Search } from "lucide-react";

export function SearchToolbar({
  placeholder = "Search or filter...",
  actions,
  value,
  onChange,
}: {
  placeholder?: string;
  actions?: ReactNode;
  value?: string;
  onChange?: (value: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative w-full max-w-[280px]">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[#8d8982]" />
        <Input
          value={value}
          onChange={(event) => onChange?.(event.target.value)}
          placeholder={placeholder}
          className="h-9 rounded-full border-[#e3e1db] bg-white pr-3 pl-9 text-[13.5px] shadow-none placeholder:text-[#9a968f] focus-visible:ring-0"
        />
      </div>
      <IconButton aria-label="Filter">
        <ListFilter className="size-4" />
      </IconButton>
      {actions ? <div className="ml-auto flex items-center gap-1.5">{actions}</div> : null}
    </div>
  );
}
