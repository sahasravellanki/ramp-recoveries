import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ChevronDown } from "lucide-react";
import type { ComponentProps } from "react";

type ButtonProps = ComponentProps<typeof Button>;

export function PrimaryButton({
  className,
  children,
  chevron,
  ...props
}: ButtonProps & { chevron?: boolean }) {
  return (
    <Button
      className={cn(
        "h-9 gap-1.5 rounded-md bg-[#e4f222] px-3 text-[13.5px] font-medium text-[#1c1c1c] shadow-none hover:bg-[#d6e60f]",
        className,
      )}
      {...props}
    >
      {children}
      {chevron ? <ChevronDown className="size-3.5 opacity-80" /> : null}
    </Button>
  );
}

export function SecondaryButton({ className, ...props }: ButtonProps) {
  return (
    <Button
      variant="outline"
      className={cn(
        "h-9 gap-1.5 rounded-md border-[#dcdad4] bg-white px-3 text-[13.5px] font-medium text-[#1c1c1c] shadow-none hover:bg-[#fafaf8]",
        className,
      )}
      {...props}
    />
  );
}

export function IconButton({ className, ...props }: ButtonProps) {
  return (
    <Button
      variant="outline"
      size="icon"
      className={cn(
        "size-9 rounded-full border-[#e1dfda] bg-white text-[#3a3a3a] shadow-none hover:bg-[#fafaf8]",
        className,
      )}
      {...props}
    />
  );
}
