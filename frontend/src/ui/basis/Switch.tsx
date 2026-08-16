import * as React from 'react'
import { cn } from './cn'

/* Switch — gestylede native checkbox (mockup/kantoor-modern.html .switch; styling in
 * styles/controls.css). Bewust géén role="switch"-override: de norm ís een native checkbox,
 * en checkbox-semantiek houdt bestaande tests (getByRole('checkbox')) en formulieren intact. */
type SwitchProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'>

export function Switch({ className, ...props }: SwitchProps) {
  return <input type="checkbox" className={cn('switch', className)} {...props} />
}
