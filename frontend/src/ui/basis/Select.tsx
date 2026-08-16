import * as React from 'react'
import { cn } from './cn'

/* Select — gestylede native select (mockup/kantoor-modern.html .sel; styling in
 * styles/controls.css). Bewust native (geen Radix-listbox): de designnorm ís een native
 * select met eigen pijl, en native semantiek houdt toetsenbord/mobiel/formulieren én de
 * bestaande tests (userEvent.selectOptions) intact. Opties als gewone <option>-children. */
type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement>

export function Select({ className, children, ...props }: SelectProps) {
  return (
    <select className={cn('sel', className)} {...props}>
      {children}
    </select>
  )
}
