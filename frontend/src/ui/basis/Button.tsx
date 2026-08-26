import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from './cn'

/* Knop — mockup/kantoor-modern.html .btn/.btn.secundair/.btn.ghost/.btn.gevaar/.icon-btn;
 * designpass v2 (26-08): pressed-state (scale .97), primaire knop met lichte schaduw, gevaar-
 * knop met eigen voorgrondtoken (--danger-fg — wit op het dark-rood haalde geen AA).
 * De oude .btn-CSS-klasse blijft bestaan voor de nog niet gemigreerde schermen; nieuw werk
 * gebruikt deze component. Semantiek-regel v2: een knop is een actie → teal, nooit status-groen. */
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-[7px] whitespace-nowrap rounded-[9px] border border-transparent font-sans text-[13px] font-semibold transition-[background-color,color,transform,box-shadow] duration-[120ms] cursor-pointer active:scale-[.97] disabled:cursor-not-allowed disabled:opacity-45 disabled:active:scale-100 focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring',
  {
    variants: {
      variant: {
        primair: 'bg-primary text-primary-fg shadow-[0_1px_2px_rgba(18,24,31,.15)] hover:bg-primary-hover',
        secundair: 'bg-panel text-text border-border hover:bg-panel-2 hover:border-faint',
        ghost: 'bg-transparent text-muted hover:bg-panel-2 hover:text-text',
        gevaar: 'bg-danger text-danger-fg hover:opacity-90',
        'warn-omlijnd': 'bg-panel text-warn border-warn hover:bg-warn-bg',
      },
      maat: {
        normaal: 'px-[15px] py-2',
        klein: 'rounded-[7px] px-[11px] py-[5px] text-[12px]',
        icoon: 'h-[34px] w-[34px] rounded-[9px] border-border bg-panel text-[15px] text-muted hover:bg-panel-2 hover:text-text',
      },
    },
    defaultVariants: { variant: 'primair', maat: 'normaal' },
  },
)

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

export function Button({ className, variant, maat, asChild = false, type, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : 'button'
  return (
    <Comp
      className={cn(buttonVariants({ variant, maat, className }))}
      {...(asChild ? {} : { type: type ?? 'button' })}
      {...props}
    />
  )
}

export { buttonVariants }
