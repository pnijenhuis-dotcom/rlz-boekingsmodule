import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

/* Breadcrumb (IA-besluit 15-08: overal breadcrumbs in het lijst→detail-patroon):
 * Werkvoorraad › [klant] › huidige laag. */
export function Breadcrumb({
  stappen,
  huidige,
}: {
  stappen: { label: string; naar: string }[]
  huidige: ReactNode
}) {
  return (
    <div className="mb-1 text-[12.5px] text-muted">
      {stappen.map((stap) => (
        <span key={stap.naar}>
          <Link to={stap.naar} className="text-primary no-underline hover:underline">
            {stap.label}
          </Link>{' '}
          <span className="text-faint">›</span>{' '}
        </span>
      ))}
      <span>{huidige}</span>
    </div>
  )
}
