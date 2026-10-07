import * as ProgressPrimitive from "@radix-ui/react-progress";
import { cn } from "../../lib/utils";

export function Progress({ value = 0, className }: { value?: number; className?: string }) {
  return <ProgressPrimitive.Root className={cn("ui-progress", className)} value={value}><ProgressPrimitive.Indicator className="ui-progress-indicator" style={{ transform: `translateX(-${100 - Math.max(0, Math.min(100, value))}%)` }} /></ProgressPrimitive.Root>;
}
