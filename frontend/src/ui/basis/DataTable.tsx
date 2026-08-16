import type { ReactNode } from 'react'
import { cn } from './cn'
import { Skeleton } from './Skeleton'

/* DataTable — de tabelvorm uit mockup/kantoor-modern.html (.kaart > .tabel-scroll > table):
 * uppercase-koppen, rij-hover, num-kolommen rechts met tabular-nums, lege-staat en
 * laad-skeleton ingebouwd. Bewust licht (geen tanstack): sorteren/filteren gebeurt in de
 * schermen zelf op de al-geladen data. */
export interface Kolom<T> {
  key: string
  kop: ReactNode
  cel: (rij: T) => ReactNode
  /** Numeriek: rechts uitgelijnd met tabular-nums. */
  num?: boolean
  breedte?: string
}

interface DataTableProps<T> {
  kolommen: Kolom<T>[]
  rijen: T[]
  rijKey: (rij: T) => string
  onRijKlik?: (rij: T) => void
  rijGeselecteerd?: (rij: T) => boolean
  leegTekst?: ReactNode
  laden?: boolean
  /** Zonder kaartrand (voor gebruik ín een bestaande kaart/paneel). */
  kaal?: boolean
  className?: string
}

export function DataTable<T>({
  kolommen,
  rijen,
  rijKey,
  onRijKlik,
  rijGeselecteerd,
  leegTekst = 'Niets gevonden.',
  laden,
  kaal,
  className,
}: DataTableProps<T>) {
  return (
    <div
      className={cn(
        'tabel-scroll',
        !kaal && 'rounded-lg border border-border bg-panel shadow-kaart',
        className,
      )}
    >
      <table className="w-full border-separate border-spacing-0 border-0 bg-transparent text-[13px]">
        <thead>
          <tr>
            {kolommen.map((k) => (
              <th
                key={k.key}
                style={k.breedte ? { width: k.breedte } : undefined}
                className={cn(
                  'whitespace-nowrap border-0 border-b border-solid border-border px-[14px] py-[10px] text-left text-[11px] font-semibold tracking-[0.06em] uppercase text-faint',
                  k.num && 'text-right',
                )}
              >
                {k.kop}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {laden && (
            <tr>
              <td colSpan={kolommen.length} className="border-0 px-[14px] py-[11px]">
                <Skeleton regels={3} />
              </td>
            </tr>
          )}
          {!laden && rijen.length === 0 && (
            <tr>
              <td
                colSpan={kolommen.length}
                className="border-0 p-[34px] text-center text-[12.5px] text-faint"
              >
                {leegTekst}
              </td>
            </tr>
          )}
          {!laden &&
            rijen.map((rij, i) => {
              const laatste = i === rijen.length - 1
              return (
                <tr
                  key={rijKey(rij)}
                  onClick={onRijKlik ? () => onRijKlik(rij) : undefined}
                  className={cn(
                    'transition-colors',
                    onRijKlik && 'cursor-pointer',
                    rijGeselecteerd?.(rij) ? 'bg-accent-bg' : 'hover:bg-panel-2',
                  )}
                >
                  {kolommen.map((k) => (
                    <td
                      key={k.key}
                      className={cn(
                        'border-0 border-solid border-border px-[14px] py-[11px] align-middle',
                        !laatste && 'border-b',
                        k.num && 'text-right font-normal tabular-nums',
                      )}
                    >
                      {k.cel(rij)}
                    </td>
                  ))}
                </tr>
              )
            })}
        </tbody>
      </table>
    </div>
  )
}

/** Hoofd+subregel in een cel (mockup td .hoofd/.sub). */
export function CelHoofdSub({ hoofd, sub }: { hoofd: ReactNode; sub?: ReactNode }) {
  return (
    <div>
      <div className="font-semibold">{hoofd}</div>
      {sub != null && sub !== '' && <div className="mt-[1px] text-[11.5px] text-muted">{sub}</div>}
    </div>
  )
}
