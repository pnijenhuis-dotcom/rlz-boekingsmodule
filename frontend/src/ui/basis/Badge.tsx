import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from './cn'

/* Badge — mockup/kantoor-modern.html .badge (+ optionele status-stip). */
const badgeVariants = cva(
  'inline-flex items-center gap-[5px] rounded-full px-[9px] py-[2px] text-[11.5px] font-semibold whitespace-nowrap',
  {
    variants: {
      variant: {
        ok: 'bg-ok-bg text-ok',
        warn: 'bg-warn-bg text-warn',
        danger: 'bg-danger-bg text-danger',
        info: 'bg-info-bg text-info',
        paars: 'bg-purple-bg text-purple',
        stil: 'border border-border bg-panel-2 text-muted',
      },
    },
    defaultVariants: { variant: 'stil' },
  },
)

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {
  /** Toon een gekleurde status-stip vóór de tekst (mockup .stip). */
  stip?: boolean
}

export function Badge({ className, variant, stip, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant, className }))} {...props}>
      {stip && <span aria-hidden className="inline-block h-[6px] w-[6px] rounded-full bg-current" />}
      {children}
    </span>
  )
}
