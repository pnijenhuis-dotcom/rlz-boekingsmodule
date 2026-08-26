import { cn } from './cn'

/* Skeleton — shimmer-laadstate (designpass v2, mockup .skeleton): dezelfde .skeleton-klasse als
 * components.css, als component zodat nieuw werk geen losse klasse-strings hoeft te kennen.
 * Regel (v2 punt 2): waar een lijst/PDF laadt staat een skeleton op de plek van de inhoud —
 * geen leeg wit en geen kale "Laden…"-regel als enige signaal. */
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

/** Drie shimmer-regels van aflopende breedte — de standaardvervanger van een "Laden…"-regel
 * bínnen een bestaand paneel/dialoog. */
export function SkeletonRegels({ regels = 3, className }: { regels?: number; className?: string }) {
  const breedtes = ['62%', '84%', '46%', '72%', '55%']
  return (
    <span className={cn('flex flex-col gap-2 py-1', className)} aria-busy="true" aria-label="Laden">
      {Array.from({ length: regels }, (_, i) => (
        <span key={i} className="skeleton" style={{ width: breedtes[i % breedtes.length] }} />
      ))}
    </span>
  )
}

/** Een compleet paneel in laadstand — voor schermen die als geheel nog laden (route-fallback,
 * detailscherm vóór de eerste respons). */
export function SkeletonPaneel({ regels = 4 }: { regels?: number }) {
  return (
    <div className="panel" aria-busy="true" aria-label="Laden">
      <span className="skeleton" style={{ width: '32%', height: 18, marginBottom: 14 }} />
      <SkeletonRegels regels={regels} />
    </div>
  )
}

/** Tabelrijen in laadstand — voor lijsten waarvan de kolommen al bekend zijn. */
export function SkeletonRijen({ kolommen, rijen = 4 }: { kolommen: number; rijen?: number }) {
  return (
    <>
      {Array.from({ length: rijen }, (_, r) => (
        <tr key={r} aria-hidden="true">
          {Array.from({ length: kolommen }, (_, k) => (
            <td key={k}>
              <span className="skeleton" style={{ width: k === 0 ? '60%' : k === kolommen - 1 ? 40 : '45%' }} />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

/** Vlakvullende shimmer voor een bijlage-/PDF-viewer die nog laadt (geen leeg wit). */
export function SkeletonBlok({ className, hoogte }: { className?: string; hoogte?: number | string }) {
  return <span className={cn('skeleton skeleton-blok', className)} style={hoogte ? { height: hoogte } : undefined} aria-busy="true" aria-label="Laden" />
}
