import type { ReactNode } from 'react'
import { cn } from '../ui/basis'

/* KPI-rij (mockup/kantoor-modern.html .kpis/.kpi, IA-besluit 15-08): klikbare kaarten =
 * kantoorbrede dwarsdoorsneden over alle klanten heen — de vervanger van de losse Vragen- en
 * Bank-tabbladen. Ook per klant herbruikbaar (mockup punt 2: het KPI-niveau leeft óók op de
 * klantpagina). */
export interface KpiKaart {
  label: string
  /** null = data (nog) niet beschikbaar — toont een em-dash i.p.v. 0. */
  waarde: number | null
  stipKleur: 'warn' | 'danger' | 'info' | 'purple'
  delta?: ReactNode
  deltaWarn?: boolean
  onClick?: () => void
}

const STIP_KLEUR: Record<KpiKaart['stipKleur'], string> = {
  warn: 'bg-warn',
  danger: 'bg-danger',
  info: 'bg-info',
  purple: 'bg-purple',
}

export function KpiRij({ kaarten, laden }: { kaarten: KpiKaart[]; laden?: boolean }) {
  return (
    <div className="mb-5 grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-3">
      {kaarten.map((kaart) => {
        const Wrapper = kaart.onClick ? 'button' : 'div'
        return (
          <Wrapper
            key={kaart.label}
            type={kaart.onClick ? 'button' : undefined}
            onClick={kaart.onClick}
            className={cn(
              'rounded-lg border border-border bg-panel px-4 py-[14px] text-left font-sans',
              kaart.onClick &&
                'cursor-pointer transition-colors hover:border-primary focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring',
            )}
          >
            <div className="flex items-center gap-[6px] text-[11.5px] text-muted">
              <span aria-hidden className={cn('inline-block h-[6px] w-[6px] rounded-full', STIP_KLEUR[kaart.stipKleur])} />
              {kaart.label}
            </div>
            <div className="mt-1 text-[22px] font-bold tracking-[-0.03em] text-text">
              {laden ? <span className="skeleton" style={{ width: 34, height: 20 }} /> : (kaart.waarde ?? '—')}
            </div>
            {!laden && kaart.delta != null && (
              <div className={cn('mt-[2px] text-[11.5px]', kaart.deltaWarn ? 'text-warn' : 'text-muted')}>
                {kaart.delta}
              </div>
            )}
          </Wrapper>
        )
      })}
    </div>
  )
}
