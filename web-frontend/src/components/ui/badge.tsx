import * as React from "react";
import { cn } from "@/lib/utils";

type BadgeTone = "neutral" | "accent" | "positive" | "negative" | "warning";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
}

const toneClasses: Record<BadgeTone, string> = {
  neutral:
    "bg-black/5 text-muted dark:bg-white/10",
  accent:
    "bg-accent/15 text-accent",
  positive:
    "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  negative:
    "bg-rose-500/15 text-rose-600 dark:text-rose-400",
  warning:
    "bg-amber-500/15 text-amber-600 dark:text-amber-400",
};

/** 상태/분류 표시용 작은 배지. */
export function Badge({ className, tone = "neutral", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
        toneClasses[tone],
        className,
      )}
      {...props}
    />
  );
}
