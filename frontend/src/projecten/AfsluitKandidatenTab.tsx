// Projecten › tab "Afsluiten? (N)" — opdracht Peter 19-09 ("welk project is afgesloten? dat onderscheid maken wij nu nog
// niet"). Eén component voor de kantoorbrede Inzicht › Projecten-lijst (administratieId = null) en de lijst per administratie
// (deeplink `?administratie=…&tab=afsluiten`). De server levert de kandidaten uit dezelfde motor als de CLI: redenen (geen
// activiteit N mnd / eindfactuur geboekt / naam zegt afgesloten / looptijd verstreken), laatste activiteit en open posten
// (chip "let op", nooit een blokkade), "Afgesloten …"-namen bovenaan. Handelen: vinkjes + "Afsluiten (N)" = per project de
// bestaande afsluit-flow mét uitkomst per rij (gelukt / bron weigerde mét reden / al afgesloten); "Niet afsluiten…" mét
// verplichte reden onthoudt het besluit tot er nieuwe activiteit is (zichtbaar onder "Toon uitgesteld (N)"). Nooit
// automatisch. Teal = actie, groen = status, oranje = let op, rood = mislukt. Tabel in `.tabel-scroll` (overflow-les 18-09).
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthOptioneel } from '../auth/AuthContext'
import { FoutMelding } from '../ui/FoutMelding'
import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Select,
  SkeletonRegels,
  useToastOptioneel,
} from '../ui/basis'
import {
  AFSLUIT_REDEN_LABEL,
  AFSLUIT_UITKOMST_LABEL,
  euro,
  haalAfsluitKandidaten,
  magAfsluitenBedienen,
  projectNietAfsluiten,
  sluitProjectenBulkAf,
  zetAfsluitStilMaanden,
  type AfsluitBulkUitkomstDto,
  type AfsluitKandidaatDto,
  type AfsluitKandidatenDto,
  type AfsluitReden,
} from './projectenApi'

const REDENEN: AfsluitReden[] = ['stil', 'eindfactuur', 'naam_afgesloten', 'looptijd_verstreken']

function isReden(w: string | null): w is AfsluitReden {
  return w !== null && (REDENEN as string[]).includes(w)
}

function datum(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(`${iso}T00:00:00`).toLocaleDateString('nl-NL')
}

const SOORT_LABEL: Record<string, string> = {
  inkoop: 'inkoop',
  verkoop: 'verkoop',
  uren: 'uren',
  planning: 'planning',
  verplichting: 'offerte',
}

function sleutel(r: { administratie_id: string; project_id: string }): string {
  return `${r.administratie_id}:${r.project_id}`
}

/** Redenen-chips per rij: informatief (stil/blauw), "naam zegt afgesloten" als let-op omdat de status het tegenspreekt. */
export function RedenChips({ rij }: { rij: AfsluitKandidaatDto }) {
  return (
    <span data-testid="reden-chips" style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
      {rij.redenen.map((r) => (
        <Badge key={r} variant={r === 'naam_afgesloten' ? 'warn' : 'info'} title={rij.reden_tekst}>
          {AFSLUIT_REDEN_LABEL[r]}
        </Badge>
      ))}
    </span>
  )
}

export function LaatsteActiviteit({ rij }: { rij: AfsluitKandidaatDto }) {
  const a = rij.laatste_activiteit
  if (!a) return <span className="hint">geen activiteit bekend</span>
  return (
    <span data-testid="laatste-activiteit">
      {SOORT_LABEL[a.soort] ?? a.soort} · {datum(a.datum)}
      {rij.stil_dagen !== null && <span className="hint"> ({rij.stil_dagen} d)</span>}
      <span className="hint" style={{ display: 'block', margin: 0, fontSize: 11 }}>
        {a.bedrag !== null ? euro(a.bedrag) : ''}
        {a.bedrag !== null && a.boekstuk ? ' · ' : ''}
        {a.boekstuk ?? ''}
      </span>
    </span>
  )
}

export function OpenPostenChip({ rij }: { rij: AfsluitKandidaatDto }) {
  const o = rij.open_posten
  if (!o.let_op) return <span className="hint">—</span>
  const delen: string[] = []
  if (o.inkoop_niet_geboekt > 0) delen.push(`${o.inkoop_niet_geboekt} inkoop niet geboekt (${euro(o.inkoop_niet_geboekt_bedrag)})`)
  if (o.verplichting_open > 0) delen.push(`${o.verplichting_open} offerte open`)
  if (o.uren_niet_gekeurd > 0) delen.push(`${o.uren_niet_gekeurd} weekstaat niet gekeurd`)
  return (
    <span data-testid="open-posten">
      <Badge variant="warn" title={delen.join(' · ')}>
        let op
      </Badge>
      <span className="hint" style={{ display: 'block', margin: 0, fontSize: 11 }}>
        {delen.join(' · ')}
      </span>
    </span>
  )
}

function UitkomstBadge({ u }: { u: AfsluitBulkUitkomstDto }) {
  const variant = u.uitkomst === 'gelukt' ? 'ok' : u.uitkomst === 'al_afgesloten' ? 'stil' : 'danger'
  return (
    <Badge variant={variant} data-testid="uitkomst" title={u.detail ?? undefined}>
      {AFSLUIT_UITKOMST_LABEL[u.uitkomst]}
      {u.detail && u.uitkomst !== 'gelukt' ? `: ${u.detail}` : ''}
    </Badge>
  )
}

function NietAfsluitenDialoog({
  projectnaam,
  onBevestig,
  onAnnuleren,
}: {
  projectnaam: string
  onBevestig: (reden: string) => void
  onAnnuleren: () => void
}) {
  const [reden, setReden] = useState('')
  const leeg = reden.trim().length === 0
  return (
    <Dialog open onOpenChange={(o) => !o && onAnnuleren()}>
      <DialogContent aria-label="Niet afsluiten">
        <DialogTitle>Niet afsluiten</DialogTitle>
        <DialogDescription>
          <b>{projectnaam}</b> verdwijnt uit &quot;Afsluiten?&quot; tot er nieuwe activiteit is (inkoop, verkoop, uren of
          planning). De reden is verplicht en komt in het logboek; je vindt de rij terug onder &quot;Toon uitgesteld&quot;.
        </DialogDescription>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block' }}>
          Reden (verplicht)
          <input
            value={reden}
            onChange={(e) => setReden(e.target.value)}
            placeholder="bijv. garantiewerk in oktober, nog een nafactuur onderweg"
            aria-label="Reden niet afsluiten"
            autoFocus
            style={{ display: 'block', width: '100%', marginTop: 4 }}
          />
        </label>
        <DialogFooter>
          <Button variant="secundair" maat="klein" onClick={onAnnuleren}>
            Annuleren
          </Button>
          <Button maat="klein" data-testid="bevestig-niet-afsluiten" disabled={leeg} onClick={() => onBevestig(reden.trim())}>
            Niet afsluiten
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function BulkDialoog({
  aantal,
  onBevestig,
  onAnnuleren,
}: {
  aantal: number
  onBevestig: (reden: string, datum: string) => void
  onAnnuleren: () => void
}) {
  const [reden, setReden] = useState('')
  const [datumWaarde, setDatum] = useState('')
  return (
    <Dialog open onOpenChange={(o) => !o && onAnnuleren()}>
      <DialogContent aria-label="Projecten afsluiten">
        <DialogTitle>
          {aantal} {aantal === 1 ? 'project' : 'projecten'} afsluiten
        </DialogTitle>
        <DialogDescription>
          Elk project gaat op afgesloten en wordt in Reeleezee/Odoo op inactief gezet (per project, met uitkomst per rij).
          Ze verdwijnen uit de keuzelijsten; een nagekomen factuur blijft boekbaar met een oranje signaal. Heropenen kan altijd
          vanaf het projectdetail.
        </DialogDescription>
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
          <label style={{ fontSize: 12, fontWeight: 600 }}>
            Afgesloten per (optioneel)
            <input type="date" value={datumWaarde} onChange={(e) => setDatum(e.target.value)} aria-label="Afgesloten per" style={{ display: 'block', width: '100%', marginTop: 4 }} />
          </label>
          <label style={{ fontSize: 12, fontWeight: 600 }}>
            Reden (optioneel, voor alle {aantal})
            <input value={reden} onChange={(e) => setReden(e.target.value)} placeholder="bijv. opgeleverd" aria-label="Reden afsluiten" style={{ display: 'block', width: '100%', marginTop: 4 }} />
          </label>
        </div>
        <DialogFooter>
          <Button variant="secundair" maat="klein" onClick={onAnnuleren}>
            Annuleren
          </Button>
          <Button variant="warn-omlijnd" maat="klein" data-testid="bevestig-bulk" onClick={() => onBevestig(reden.trim(), datumWaarde)}>
            Afsluiten ({aantal})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function StilVensterInstelling({
  administratieId,
  waarde,
  magHandelen,
  onGewijzigd,
}: {
  administratieId: string
  waarde: number
  magHandelen: boolean
  onGewijzigd: () => void
}) {
  const [bewerk, setBewerk] = useState(false)
  const [maanden, setMaanden] = useState(waarde)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const { meld } = useToastOptioneel()
  useEffect(() => setMaanden(waarde), [waarde])
  if (!bewerk) {
    return (
      <span className="hint" data-testid="stil-venster">
        Stil-venster: {waarde} {waarde === 1 ? 'maand' : 'maanden'}
        {magHandelen && (
          <>
            {' · '}
            <button type="button" className="linkbtn" onClick={() => setBewerk(true)} data-testid="stil-venster-wijzig">
              wijzig
            </button>
          </>
        )}
      </span>
    )
  }
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }} data-testid="stil-venster-bewerk">
      <label className="hint" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
        Stil-venster
        <input
          type="number"
          min={1}
          max={36}
          value={maanden}
          aria-label="Stil-venster in maanden"
          onChange={(e) => setMaanden(Number(e.target.value))}
          style={{ width: 64 }}
        />
        mnd
      </label>
      <Button
        maat="klein"
        disabled={bezig || maanden < 1 || maanden > 36}
        onClick={() => {
          setBezig(true)
          setFout(null)
          zetAfsluitStilMaanden(administratieId, maanden)
            .then(() => {
              meld(`Stil-venster op ${maanden} maanden gezet.`, 'ok')
              setBewerk(false)
              onGewijzigd()
            })
            .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
            .finally(() => setBezig(false))
        }}
      >
        Opslaan
      </Button>
      <button type="button" className="linkbtn" onClick={() => setBewerk(false)}>
        annuleren
      </button>
      {fout && <span style={{ color: 'var(--danger)', fontSize: 12 }}>{fout}</span>}
    </span>
  )
}

export function AfsluitKandidatenTab({
  administratieId,
  onAantal,
}: {
  /** null = kantoorbreed over alle administraties in scope; anders de lijst van één administratie. */
  administratieId: string | null
  /** Teller voor de tab-kop "Afsluiten? (N)" — dezelfde bron als de tabel. */
  onAantal?: (n: number) => void
}) {
  const auth = useAuthOptioneel()
  const magHandelen = magAfsluitenBedienen(auth?.rol)
  const { meld } = useToastOptioneel()
  const [zoek, setZoek] = useState('')
  const [reden, setReden] = useState<AfsluitReden | null>(null)
  const [toonUitgesteld, setToonUitgesteld] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [data, setData] = useState<AfsluitKandidatenDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [versie, setVersie] = useState(0)
  const [gekozen, setGekozen] = useState<Set<string>>(new Set())
  const [uitkomsten, setUitkomsten] = useState<Record<string, AfsluitBulkUitkomstDto>>({})
  const [bulkOpen, setBulkOpen] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [nietAfsluiten, setNietAfsluiten] = useState<AfsluitKandidaatDto | null>(null)

  useEffect(() => {
    let actueel = true
    setLaadFout(null)
    const timer = window.setTimeout(
      () => {
        haalAfsluitKandidaten({ administratieId, q: zoek.trim(), reden, toonUitgesteld, pagina })
          .then((d) => {
            if (!actueel) return
            setData(d)
            onAantal?.(d.tellers.kandidaten)
          })
          .catch((err: unknown) => {
            if (actueel) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
          })
      },
      zoek ? 250 : 0,
    )
    return () => {
      actueel = false
      window.clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [administratieId, zoek, reden, toonUitgesteld, pagina, versie])

  const rijen = data?.rijen ?? []
  const zichtbareSleutels = useMemo(() => rijen.map(sleutel), [rijen])
  const gekozenZichtbaar = zichtbareSleutels.filter((s) => gekozen.has(s))
  const allesGekozen = zichtbareSleutels.length > 0 && gekozenZichtbaar.length === zichtbareSleutels.length
  const paginas = Math.max(1, Math.ceil((data?.totaal ?? 0) / (data?.per_pagina ?? 50)))

  const herlaad = () => setVersie((v) => v + 1)

  const wissel = (s: string) =>
    setGekozen((g) => {
      const n = new Set(g)
      if (n.has(s)) n.delete(s)
      else n.add(s)
      return n
    })

  const bulk = (redenTekst: string, datumWaarde: string) => {
    const items = rijen.filter((r) => gekozen.has(sleutel(r))).map((r) => ({ administratie_id: r.administratie_id, project_id: r.project_id }))
    setBulkOpen(false)
    setBezig(true)
    sluitProjectenBulkAf(items, { reden: redenTekst || null, datum: datumWaarde || null })
      .then((res) => {
        const map: Record<string, AfsluitBulkUitkomstDto> = {}
        for (const u of res.uitkomsten) map[sleutel(u)] = u
        setUitkomsten((oud) => ({ ...oud, ...map }))
        setGekozen(new Set())
        meld(
          res.mislukt === 0
            ? `${res.gelukt} ${res.gelukt === 1 ? 'project' : 'projecten'} afgesloten.`
            : `${res.gelukt} afgesloten, ${res.mislukt} niet — zie de uitkomst per rij.`,
          res.mislukt === 0 ? 'ok' : 'warn',
        )
        herlaad()
      })
      .catch((err: unknown) => {
        meld(err instanceof Error ? err.message : 'Afsluiten mislukt', 'warn')
      })
      .finally(() => setBezig(false))
  }

  const nietAfsluitenBevestig = (rij: AfsluitKandidaatDto, redenTekst: string) => {
    setNietAfsluiten(null)
    projectNietAfsluiten(rij.administratie_id, rij.project_id, redenTekst)
      .then(() => {
        meld(`${rij.naam ?? 'Project'} blijft open — staat onder "Toon uitgesteld".`, 'ok')
        setGekozen((g) => {
          const n = new Set(g)
          n.delete(sleutel(rij))
          return n
        })
        herlaad()
      })
      .catch((err: unknown) => meld(err instanceof Error ? err.message : 'Opslaan mislukt', 'warn'))
  }

  // Rijen mét een verse uitkomst tonen we (kort) nog in de tabel — de herlading haalt afgesloten rijen weg; de uitkomst
  // blijft als aparte lijst zichtbaar zodat niets stil verdwijnt.
  const uitkomstLijst = Object.values(uitkomsten)

  return (
    <div data-testid="afsluit-tab">
      <div
        className="p-kop"
        style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}
      >
        <input
          type="search"
          aria-label="Zoek kandidaat"
          placeholder="🔍 project of administratie…"
          value={zoek}
          onChange={(e) => {
            setZoek(e.target.value)
            setPagina(1)
          }}
          style={{ width: 220, maxWidth: '100%' }}
        />
        <Select
          aria-label="Filter op reden"
          value={reden ?? ''}
          onChange={(e) => {
            const w = e.target.value
            setReden(isReden(w) ? w : null)
            setPagina(1)
          }}
          style={{ width: 'auto' }}
        >
          <option value="">Reden: alle{data ? ` (${data.tellers.kandidaten})` : ''}</option>
          {REDENEN.map((r) => (
            <option key={r} value={r}>
              Reden: {AFSLUIT_REDEN_LABEL[r]}
              {data ? ` (${data.tellers.per_reden[r] ?? 0})` : ''}
            </option>
          ))}
        </Select>
        {data && data.tellers.let_op > 0 && (
          <Badge variant="warn" data-testid="chip-let-op" title="Kandidaten met inkoop nog niet geboekt, een open offerte of ongekeurde uren — informatie, geen blokkade">
            {data.tellers.let_op} met open posten
          </Badge>
        )}
        {data && data.tellers.uitgesteld > 0 && (
          <button
            type="button"
            className="linkbtn"
            data-testid="toggle-uitgesteld"
            aria-pressed={toonUitgesteld}
            onClick={() => {
              setToonUitgesteld((t) => !t)
              setPagina(1)
            }}
          >
            {toonUitgesteld ? 'Terug naar kandidaten' : `Toon uitgesteld (${data.tellers.uitgesteld})`}
          </button>
        )}
        <span style={{ marginLeft: 'auto' }} />
        {administratieId && data && data.stil_maanden !== null && (
          <StilVensterInstelling administratieId={administratieId} waarde={data.stil_maanden} magHandelen={magHandelen} onGewijzigd={herlaad} />
        )}
        {magHandelen && !toonUitgesteld && (
          <Button
            variant="warn-omlijnd"
            maat="klein"
            data-testid="knop-bulk-afsluiten"
            disabled={gekozenZichtbaar.length === 0 || bezig}
            onClick={() => setBulkOpen(true)}
          >
            Afsluiten ({gekozenZichtbaar.length})
          </Button>
        )}
      </div>

      {laadFout && <FoutMelding melding="De afsluit-kandidaten konden niet geladen worden." detail={laadFout} onOpnieuw={herlaad} />}
      {data === null && !laadFout && (
        <div style={{ padding: 16 }}>
          <SkeletonRegels />
        </div>
      )}
      {data !== null && rijen.length === 0 && (
        <div className="hint" style={{ padding: '14px 18px' }} data-testid="afsluit-leeg">
          {toonUitgesteld
            ? 'Geen uitgestelde projecten.'
            : reden
              ? `Geen kandidaten met reden "${AFSLUIT_REDEN_LABEL[reden]}".`
              : zoek.trim()
                ? `Geen kandidaten gevonden voor "${zoek.trim()}".`
                : 'Geen projecten die klaar lijken om af te sluiten — alles heeft recente activiteit, geen eindfactuur, geen verstreken looptijd en geen "Afgesloten"-naam.'}
        </div>
      )}
      {rijen.length > 0 && (
        <div className="tabel-scroll">
          <table data-testid="afsluit-tabel">
            <thead>
              <tr>
                {magHandelen && !toonUitgesteld && (
                  <th style={{ width: 36 }}>
                    <Checkbox
                      aria-label="Alles op deze pagina kiezen"
                      checked={allesGekozen}
                      indeterminate={!allesGekozen && gekozenZichtbaar.length > 0}
                      onChange={() =>
                        setGekozen((g) => {
                          const n = new Set(g)
                          if (allesGekozen) zichtbareSleutels.forEach((s) => n.delete(s))
                          else zichtbareSleutels.forEach((s) => n.add(s))
                          return n
                        })
                      }
                    />
                  </th>
                )}
                {!administratieId && <th style={{ width: '15%' }}>Administratie</th>}
                <th>Project</th>
                <th style={{ width: 210 }}>Reden</th>
                <th style={{ width: 190 }}>Laatste activiteit</th>
                <th style={{ width: 200 }}>{toonUitgesteld ? 'Niet afsluiten omdat' : 'Open posten'}</th>
                <th style={{ width: 200 }} />
              </tr>
            </thead>
            <tbody>
              {rijen.map((r) => {
                const s = sleutel(r)
                const uitkomst = uitkomsten[s]
                return (
                  <tr key={s} data-testid="afsluit-rij">
                    {magHandelen && !toonUitgesteld && (
                      <td>
                        <Checkbox aria-label={`Kies ${r.naam ?? r.project_id}`} checked={gekozen.has(s)} onChange={() => wissel(s)} disabled={bezig} />
                      </td>
                    )}
                    {!administratieId && (
                      <td>
                        <Link to={`/projecten?administratie=${r.administratie_id}&tab=afsluiten`} className="text-primary no-underline hover:underline">
                          {r.administratie_naam}
                        </Link>
                      </td>
                    )}
                    <td>
                      <b>{r.naam ?? r.project_id}</b>
                      {r.looptijd_tot && <div className="hint" style={{ margin: '2px 0 0', fontSize: 11.5 }}>looptijd tot {datum(r.looptijd_tot)}</div>}
                    </td>
                    <td>
                      <RedenChips rij={r} />
                    </td>
                    <td>
                      <LaatsteActiviteit rij={r} />
                    </td>
                    <td>
                      {toonUitgesteld && r.uitstel ? (
                        <span data-testid="uitstel">
                          {r.uitstel.reden}
                          <span className="hint" style={{ display: 'block', margin: 0, fontSize: 11 }}>
                            sinds {new Date(r.uitstel.op).toLocaleDateString('nl-NL')}
                          </span>
                        </span>
                      ) : (
                        <OpenPostenChip rij={r} />
                      )}
                    </td>
                    <td className="acties" style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                      {uitkomst && <UitkomstBadge u={uitkomst} />}
                      {!uitkomst && magHandelen && !toonUitgesteld && (
                        <button type="button" className="linkbtn" data-testid="knop-niet-afsluiten" onClick={() => setNietAfsluiten(r)}>
                          Niet afsluiten…
                        </button>
                      )}{' '}
                      <Link to={`/projecten/${r.administratie_id}/${r.project_id}`} className="btn secondary" aria-label={`Open project ${r.naam ?? r.project_id}`}>
                        Openen →
                      </Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {uitkomstLijst.length > 0 && (
        <div className="hint" data-testid="uitkomst-overzicht" style={{ padding: '10px 14px', borderTop: '1px solid var(--border)' }}>
          Laatste bulk-actie:{' '}
          {uitkomstLijst.map((u) => (
            <span key={sleutel(u)} style={{ marginRight: 8 }}>
              {u.naam ?? u.project_id} <UitkomstBadge u={u} />
            </span>
          ))}
        </div>
      )}
      {data && (
        <div
          className="voet hint"
          data-testid="afsluit-voet"
          style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}
        >
          <Button variant="ghost" maat="klein" aria-label="Vorige pagina" disabled={pagina <= 1} onClick={() => setPagina((p) => p - 1)}>
            ‹
          </Button>
          <span>
            {pagina} van {paginas}
          </span>
          <Button variant="ghost" maat="klein" aria-label="Volgende pagina" disabled={pagina >= paginas} onClick={() => setPagina((p) => p + 1)}>
            ›
          </Button>
          <span>
            · {data.totaal} {toonUitgesteld ? 'uitgesteld' : data.totaal === 1 ? 'kandidaat' : 'kandidaten'}
            {!administratieId ? ` over ${data.tellers.administraties} ${data.tellers.administraties === 1 ? 'administratie' : 'administraties'}` : ''}
            {' · afsluiten blijft een klik van jou, nooit automatisch'}
          </span>
        </div>
      )}

      {bulkOpen && <BulkDialoog aantal={gekozenZichtbaar.length} onBevestig={bulk} onAnnuleren={() => setBulkOpen(false)} />}
      {nietAfsluiten && (
        <NietAfsluitenDialoog
          projectnaam={nietAfsluiten.naam ?? nietAfsluiten.project_id}
          onBevestig={(redenTekst) => nietAfsluitenBevestig(nietAfsluiten, redenTekst)}
          onAnnuleren={() => setNietAfsluiten(null)}
        />
      )}
    </div>
  )
}
