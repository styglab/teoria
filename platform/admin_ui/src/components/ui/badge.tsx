import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

const badgeVariants = cva("ui-badge", { variants: { variant: { default: "ui-badge-default", success: "ui-badge-success", warning: "ui-badge-warning", destructive: "ui-badge-destructive", outline: "ui-badge-outline" } }, defaultVariants: { variant: "default" } });
export function Badge({ className, variant, ...props }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) { return <span className={cn(badgeVariants({ variant }), className)} {...props} />; }
