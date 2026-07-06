import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/** 회전하는 로딩 스피너. */
export function Spinner({ className }: { className?: string }) {
  return (
    <Loader2
      className={cn("animate-spin", className)}
      aria-hidden="true"
    />
  );
}
