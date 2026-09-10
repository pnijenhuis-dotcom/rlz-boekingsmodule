import { useId, useMemo, useState, type KeyboardEvent } from 'react'
import { BevestigDialog } from '../instellingen/BevestigDialog'
import { Badge, Button, Checkbox, cn } from '../ui/basis'

/* ScopeLijst (blok 2 nachtrun 10/11-09, kliktest Peter 10-09 avond met 71 administraties): één doorzoekbare
 * lijst met álle administraties en een vinkje per rij, over de volledige dialooghoogte (min. 12 rijen zichtbaar,
 * intern scrollend) — de chips-wolk onder de oude MultiSelect is weg. Bovenin: teller "N van M geselecteerd",
 * filter "alleen geselecteerde", knoppen Alles / Geen ("Geen" vraagt bevestiging zodra er al scope stond — RLS:
 * geen scope = niets zien). Gearchiveerde administraties staan onderaan mét status-chip. De volgorde blijft
 * alfabetisch, óók na aanvinken (besluit Peter: hersorteren zou de lijst bij elke klik laten springen); een
 * aangevinkte rij draagt de bestaande scope-chip-kleur (--accent-bg / --primary). Gedeeld door de kantoor-
 * scope-dialoog (ScopeModal) en de accordeur-variant "Administraties toevoegen…". Toegankelijk als native
 * checkboxes in een role="group" (Tab/Spatie werken zonder aria-vertaalslag; zelfde testconventie als de
 * MultiSelect); pijl-omlaag vanuit het zoekveld springt naar de eerste rij. */

export interface ScopeLijstItem {
  id: string
  naam: string
  /** false = gearchiveerd: onderaan, mét chip; nooit via "Alles" aangevinkt. */
  actief: boolean
}

export interface ScopeVerschil {
  erbij: string[]
  eraf: string[]
}

export const SCOPELIJST_RIJHOOGTE_PX = 34
export const SCOPELIJST_MIN_RIJEN = 12

const collator = new Intl.Collator('nl', { sensitivity: 'base', numeric: true })

/** Alfabetisch op naam; gearchiveerde administraties als apart blok onderaan. */
export function sorteerScopeItems(items: ScopeLijstItem[]): ScopeLijstItem[] {
  return [...items].sort((a, b) => {
    if (a.actief !== b.actief) return a.actief ? -1 : 1
    return collator.compare(a.naam, b.naam)
  })
}

export function berekenVerschil(oorspronkelijk: string[], nieuw: string[]): ScopeVerschil {
  const was = new Set(oorspronkelijk)
  const wordt = new Set(nieuw)
  return {
    erbij: nieuw.filter((id) => !was.has(id)),
    eraf: oorspronkelijk.filter((id) => !wordt.has(id)),
  }
}

/** "+3 −1" — alleen de delen die niet nul zijn; leeg als er geen verschil is. */
export function verschilTekst(v: ScopeVerschil): string {
  const delen: string[] = []
  if (v.erbij.length > 0) delen.push(`+${v.erbij.length}`)
  if (v.eraf.length > 0) delen.push(`−${v.eraf.length}`)
  return delen.join(' ')
}

/** "A, B, C en 4 andere" — max `max` namen uitgeschreven. */
export function namenOpsomming(namen: string[], max = 10): string {
  if (namen.length <= max) return namen.join(', ')
  const rest = namen.length - max
  return `${namen.slice(0, max).join(', ')} en ${rest} andere`
}

function normaliseer(s: string): string {
  return s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
}

interface Props {
  items: ScopeLijstItem[]
  geselecteerd: string[]
  onChange: (ids: string[]) => void
  /** De scope zoals die vóór het openen stond — "Geen" vraagt bevestiging als dit niet leeg is. */
  oorspronkelijk?: string[]
  /** Rijen die aangevinkt en vergrendeld zijn (bv. "heeft al toegang" in de accordeur-variant). */
  vergrendeld?: ReadonlySet<string>
  vergrendeldLabel?: string
  disabled?: boolean
  zoekPlaceholder?: string
  /** Wat er in de "Geen"-bevestiging staat (wie/wat verliest wat). */
  geenBevestigingTekst?: string
  'data-testid'?: string
}

export function ScopeLijst({
  items,
  geselecteerd,
  onChange,
  oorspronkelijk = [],
  vergrendeld,
  vergrendeldLabel = 'heeft al toegang',
  disabled,
  zoekPlaceholder = 'Zoek administratie…',
  geenBevestigingTekst,
  'data-testid': testId = 'scope-lijst',
}: Props) {
  const [zoek, setZoek] = useState('')
  const [alleenGeselecteerde, setAlleenGeselecteerde] = useState(false)
  const [geenBevestiging, setGeenBevestiging] = useState(false)
  const lijstId = useId()

  const gesorteerd = useMemo(() => sorteerScopeItems(items), [items])
  const gekozen = useMemo(() => new Set(geselecteerd), [geselecteerd])
  const isVergrendeld = (id: string) => Boolean(vergrendeld?.has(id))

  const term = normaliseer(zoek.trim())
  const zichtbaar = useMemo(
    () =>
      gesorteerd.filter((it) => {
        if (alleenGeselecteerde && !gekozen.has(it.id)) return false
        if (term && !normaliseer(it.naam).includes(term)) return false
        return true
      }),
    [gesorteerd, alleenGeselecteerde, gekozen, term],
  )

  // Teller over de kiesbare rijen; vergrendelde rijen tellen apart ("K hebben al toegang").
  const kiesbaar = gesorteerd.filter((it) => !isVergrendeld(it.id))
  const aantalGekozen = kiesbaar.filter((it) => gekozen.has(it.id)).length
  const aantalVergrendeld = gesorteerd.length - kiesbaar.length

  function wissel(id: string, aan: boolean) {
    if (isVergrendeld(id)) return
    onChange(aan ? [...geselecteerd, id] : geselecteerd.filter((x) => x !== id))
  }

  /** "Alles" = alle zichtbare, actieve, kiesbare rijen erbij (gearchiveerd nooit in bulk). */
  function alles() {
    const erbij = zichtbaar.filter((it) => it.actief && !isVergrendeld(it.id) && !gekozen.has(it.id)).map((it) => it.id)
    if (erbij.length > 0) onChange([...geselecteerd, ...erbij])
  }
  const allesMogelijk = zichtbaar.some((it) => it.actief && !isVergrendeld(it.id) && !gekozen.has(it.id))

  /** "Geen" = alle zichtbare kiesbare rijen eraf; met bevestiging als er al scope stond. */
  function geenUitvoeren() {
    const weg = new Set(zichtbaar.filter((it) => !isVergrendeld(it.id)).map((it) => it.id))
    onChange(geselecteerd.filter((id) => !weg.has(id)))
    setGeenBevestiging(false)
  }
  function geen() {
    if (oorspronkelijk.length > 0) setGeenBevestiging(true)
    else geenUitvoeren()
  }
  const geenMogelijk = zichtbaar.some((it) => !isVergrendeld(it.id) && gekozen.has(it.id))

  const eersteRijFocus = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'ArrowDown') return
    const lijst = document.getElementById(lijstId)
    const eerste = lijst?.querySelector<HTMLInputElement>('input[type="checkbox"]:not(:disabled)')
    if (eerste) {
      e.preventDefault()
      eerste.focus()
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid={testId}>
      <input
        type="text"
        value={zoek}
        onChange={(e) => setZoek(e.target.value)}
        onKeyDown={eersteRijFocus}
        placeholder={zoekPlaceholder}
        aria-label={zoekPlaceholder}
        disabled={disabled}
        className="w-full min-w-0"
      />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]">
        <span className="font-semibold" data-testid="scope-teller">
          {aantalGekozen} van {kiesbaar.length} geselecteerd
          {aantalVergrendeld > 0 && (
            <span className="font-normal text-muted">
              {' '}
              · {aantalVergrendeld} {aantalVergrendeld === 1 ? 'heeft' : 'hebben'} al toegang
            </span>
          )}
        </span>
        <label className="m-0 inline-flex cursor-pointer items-center gap-[6px] font-normal text-muted">
          <Checkbox
            checked={alleenGeselecteerde}
            onChange={(e) => setAlleenGeselecteerde(e.target.checked)}
            disabled={disabled}
          />
          alleen geselecteerde
        </label>
        <span className="ml-auto inline-flex items-center gap-1">
          <Button variant="ghost" maat="klein" onClick={alles} disabled={disabled || !allesMogelijk} aria-label="Alles selecteren">
            Alles
          </Button>
          <Button variant="ghost" maat="klein" onClick={geen} disabled={disabled || !geenMogelijk} aria-label="Geen selecteren">
            Geen
          </Button>
        </span>
      </div>
      <div
        id={lijstId}
        role="group"
        aria-label="Administraties"
        data-testid="scope-lijst-rijen"
        className="scope-lijst-rijen min-w-0 overflow-y-auto overflow-x-hidden rounded-[9px] border border-border bg-panel"
        data-min-rijen={SCOPELIJST_MIN_RIJEN}
        style={{
          // Min. 12 rijen (jsdom-leesbaar als kale px), groeit mee met het venster tot 620 px.
          minHeight: SCOPELIJST_MIN_RIJEN * SCOPELIJST_RIJHOOGTE_PX,
          height: `clamp(${SCOPELIJST_MIN_RIJEN * SCOPELIJST_RIJHOOGTE_PX}px, 60vh, 680px)`,
        }}
      >
        {zichtbaar.length === 0 && (
          <div className="px-[11px] py-[10px] text-[12.5px] text-faint">
            {alleenGeselecteerde && !term
              ? 'Nog niets geselecteerd.'
              : term
                ? `Geen administratie gevonden voor "${zoek.trim()}".`
                : 'Geen administraties.'}
          </div>
        )}
        {zichtbaar.map((it) => {
          const aan = gekozen.has(it.id)
          const slot = isVergrendeld(it.id)
          return (
            <label
              key={it.id}
              data-testid="scope-rij"
              data-geselecteerd={aan ? 'ja' : 'nee'}
              className={cn(
                'm-0 flex min-w-0 cursor-pointer items-center gap-[9px] border-b border-border/50 px-[11px] text-[12.5px] font-normal text-text hover:bg-panel-2',
                aan && !slot && 'bg-accent-bg font-semibold text-primary',
                slot && 'cursor-default bg-panel-2 text-muted',
                !it.actief && !aan && 'text-muted',
              )}
              style={{ height: SCOPELIJST_RIJHOOGTE_PX }}
            >
              <Checkbox
                checked={aan || slot}
                onChange={(e) => wissel(it.id, e.target.checked)}
                disabled={disabled || slot}
                aria-label={it.actief ? it.naam : `${it.naam} — gearchiveerd`}
              />
              <span className="min-w-0 flex-1 truncate" title={it.naam}>
                {it.naam}
              </span>
              {!it.actief && <Badge variant="stil">gearchiveerd</Badge>}
              {slot && <Badge variant="stil">{vergrendeldLabel}</Badge>}
            </label>
          )
        })}
      </div>
      {geenBevestiging && (
        <BevestigDialog
          titel="Alle administraties uit de selectie halen?"
          bericht={
            geenBevestigingTekst ??
            `Zonder scope ziet een medewerker niets — de toegang wordt op databaseniveau afgedwongen (RLS). Dit haalt ${aantalGekozen} ${aantalGekozen === 1 ? 'administratie' : 'administraties'} uit de selectie; de wijziging gaat pas door bij opslaan en wordt geauditeerd.`
          }
          bezig={false}
          fout={null}
          onBevestigen={geenUitvoeren}
          onAnnuleren={() => setGeenBevestiging(false)}
        />
      )}
    </div>
  )
}
