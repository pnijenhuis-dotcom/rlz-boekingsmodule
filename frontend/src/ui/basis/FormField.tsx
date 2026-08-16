import type { ReactNode } from 'react'
import { cn } from './cn'

/* FormField — labelregel + control + hint/foutregel (mockup/kantoor-modern.html .veld).
 * De control zelf komt als kind (Select/Checkbox/input/…); id-koppeling via htmlFor. */
interface FormFieldProps {
  label: ReactNode
  htmlFor?: string
  hint?: ReactNode
  fout?: string
  /** Optionele actie rechts in de labelregel. */
  labelActie?: ReactNode
  className?: string
  children: ReactNode
}

export function FormField({ label, htmlFor, hint, fout, labelActie, className, children }: FormFieldProps) {
  return (
    <div className={cn('mb-[13px]', className)}>
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={htmlFor} className="mb-[5px] block text-[12px] font-semibold text-text">
          {label}
        </label>
        {labelActie}
      </div>
      {children}
      {hint && !fout && <div className="mt-1 text-[11.5px] text-faint">{hint}</div>}
      {fout && <div className="mt-1 text-[11.5px] font-semibold text-danger">{fout}</div>}
    </div>
  )
}
