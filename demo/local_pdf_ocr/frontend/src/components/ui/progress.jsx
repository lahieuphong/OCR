"use client";
import { cn } from "@/lib/utils";
import * as ProgressPrimitive from "@radix-ui/react-progress";
function Progress({
  className,
  value,
  ...props
}) {
  return <ProgressPrimitive.Root
    data-slot="progress"
    value={value}
    className={cn(
      "relative h-2 w-full overflow-hidden rounded-full bg-primary/20",
      className
    )}
    {...props}
  >
      <ProgressPrimitive.Indicator
    data-slot="progress-indicator"
    className="h-full w-full flex-1 bg-primary transition-all"
    style={value == null ? undefined : { transform: `translateX(-${100 - value}%)` }}
  />
    </ProgressPrimitive.Root>;
}
export {
  Progress
};
