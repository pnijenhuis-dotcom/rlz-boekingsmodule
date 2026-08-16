import { cn } from './cn'

/* Skeleton — dezelfde rustige puls als de bestaande .skeleton-klasse (components.css), als
 * component zodat nieuw werk geen losse klasse-strings hoeft te kennen. */
export function Skeleton({ className, regels = 1 }: { className?: string; regels?: number }) {
  if (regels <= 1) return <span className={cn('skeleton', className)} />
  return (
    <span className="flex flex-col gap-2">
      {Array.from({ length: regels }, (_, i) => (
        <span key={i} className={cn('skeleton', className)} />
      ))}
    </span>
  )
}
