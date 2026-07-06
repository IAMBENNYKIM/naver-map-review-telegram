import * as React from "react";
import { cn } from "@/lib/utils";

type LabelProps = React.LabelHTMLAttributes<HTMLLabelElement>;

/** 폼 필드용 라벨. htmlFor 로 입력과 명시적으로 연결해 접근성을 확보한다. */
export const Label = React.forwardRef<HTMLLabelElement, LabelProps>(
  ({ className, ...props }, ref) => {
    return (
      <label
        ref={ref}
        className={cn("text-sm font-medium text-foreground", className)}
        {...props}
      />
    );
  },
);
Label.displayName = "Label";
