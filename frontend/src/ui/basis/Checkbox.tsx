import * as React from 'react'
import { cn } from './cn'

/* Checkbox — gestylede native input (mockup/kantoor-modern.html .cb; styling in
 * styles/controls.css). Native semantiek: werkt met labels, formulieren en de bestaande
 * testsuite (toBeChecked/userEvent.click) zonder aria-vertaalslag. */
type CheckboxProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> & {
  /** Zet de visuele indeterminate-stand (niet via een attribuut te zetten op natives). */
  indeterminate?: boolean
}

export function Checkbox({ className, indeterminate, ...props }: CheckboxProps) {
  const ref = React.useRef<HTMLInputElement>(null)
  React.useEffect(() => {
    if (ref.current) ref.current.indeterminate = Boolean(indeterminate)
  }, [indeterminate])
  return <input ref={ref} type="checkbox" className={cn('cb', className)} {...props} />
}
