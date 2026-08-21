import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError, apiFetch } from '../api/client'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { Breadcrumb } from '../werkvoorraad/Breadcrumb'
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  FormField,
  Select,
  useToastOptioneel,
} from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import {
  eenheidLabel,
  haalContractToets,
  haalMeerwerkLijst,
  keurMeerwerkGoed,
  markeerDoorbelast,
  meerwerkFotoUrl,
  stelMeerwerkVraag,
  wijsMeerwerkAf,
  type MeerwerkDto,
  type StaffelRegelDto,
} from './meerwerkApi'

/* Meerwerk-deelscherm (fase 3, mockup meerwerk-kantoor.html — 1-op-1): klantpagina-stand →
 * deze lijst (statusfilters, omschrijvingen ALTIJD voluit — regelterugloop, nooit afgekapt) →
 * beoordeel-zijpaneel met contract-toets als VOORSTEL (mens bevestigt de prijs, nooit
 * auto-boeken). Toegang: module-recht "Meerwerk & urenstaten" (server-side; 403 → nette
 * melding), klantscope blijft eronder gelden. */

type Filter = 'gemeld' | 'goedgekeurd' | 'doorbelast' | 'afgewezen'

const FILTER_LABELS: Record<Filter, string> = {
  gemeld: 'Te beoordelen',
  goedgekeurd: 'Goedgekeurd, nog doorbelasten',
  doorbelast: 'Doorbelast',
  afgewezen: 'Afgewezen',
}

function statusBadge(item: MeerwerkDto) {
  switch (item.status) {
    case 'gemeld':
      return <Badge variant="paars">gemeld</Badge>
    case 'goedgekeurd':
      return <Badge variant="warn">nog doorbelasten</Badge>
    case 'doorbelast':
      return <Badge variant="ok">doorbelast{item.verkoopfactuur_referentie ? ` · ${item.verkoopfactuur_referentie}` : ''}</Badge>
    case 'afgewezen':
      return <Badge variant="danger">afgewezen · eigen rekening</Badge>
  }
}

function datumLabel(iso: string): string {
  return new Date(iso).toLocaleDateString('nl-NL', { day: 'numeric', month: 'short' })
}

function euro(bedrag: string | null): string {
  if (bedrag === null) return '—'
  return `€ ${Number(bedrag).toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function MeerwerkScreen() {
  const [searchParams] = useSearchParams()
  const administratieId = searchParams.get('administratie')
  const { administraties } = useAdministraties()
  const { meld } = useToastOptioneel()

  const [items, setItems] = useState<MeerwerkDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [geenRecht, setGeenRecht] = useState(false)
  const [filter, setFilter] = useState<Filter>('gemeld')
  const [projectFilter, setProjectFilter] = useState<string>('')
  const [openItem, setOpenItem] = useState<MeerwerkDto | null>(null)

  const administratieNaam = useMemo(
    () => (administraties ?? []).find((a) => a.id === administratieId)?.naam ?? 'Administratie',
    [administraties, administratieId],
  )

  const laad = useCallback(() => {
    if (!administratieId) return
    setFout(null)
    haalMeerwerkLijst(administratieId)
      .then(setItems)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) setGeenRecht(true)
        else setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
  }, [administratieId])

  useEffect(() => {
    setItems(null)
    laad()
  }, [laad])

  if (!administratieId) {
    return <p className="hint">Geen administratie gekozen — open meerwerk vanaf de klantpagina.</p>
  }
  if (geenRecht) {
    return (
      <p className="hint">
        Meerwerk &amp; urenstaten vereist een module-recht — een Beheerder kent dit toe onder Gebruikers &amp; toegang.
      </p>
    )
  }

  const tellers = new Map<Filter, number>()
  for (const f of Object.keys(FILTER_LABELS) as Filter[]) {
    tellers.set(f, (items ?? []).filter((i) => i.status === f).length)
  }
  const projecten = Array.from(
    new Map((items ?? []).map((i) => [i.project_id, i.project_naam ?? i.project_id])).entries(),
  )
  const zichtbaar = (items ?? []).filter(
    (i) => i.status === filter && (projectFilter === '' || i.project_id === projectFilter),
  )

  return (
    <div>
      <div className="topbar">
        <div>
          <Breadcrumb
            stappen={[
              { label: 'Werkvoorraad', naar: '/' },
              { label: administratieNaam, naar: `/?administratie=${administratieId}` },
            ]}
            huidige="Meerwerk"
          />
          <h1>Meerwerk — {administratieNaam}</h1>
          <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
            Gemeld door uitvoerders in de app · niets verdwijnt stil: elke melding houdt een status
          </div>
        </div>
      </div>

      {fout && <FoutMelding melding="Het meerwerk kon niet geladen worden." detail={fout} onOpnieuw={laad} />}

      <div className="panel">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
          <div className="segment" role="group" aria-label="Filter op status">
            {(Object.keys(FILTER_LABELS) as Filter[]).map((f) => (
              <button key={f} className={filter === f ? 'actief' : undefined} onClick={() => setFilter(f)}>
                {FILTER_LABELS[f]} ({tellers.get(f) ?? 0})
              </button>
            ))}
          </div>
          <div style={{ marginLeft: 'auto' }}>
            <Select
              aria-label="Filter op project"
              value={projectFilter}
              onChange={(e) => setProjectFilter(e.target.value)}
            >
              <option value="">Alle projecten</option>
              {projecten.map(([id, naam]) => (
                <option key={id} value={id}>
                  {naam}
                </option>
              ))}
            </Select>
          </div>
        </div>

        {items === null && !fout && (
          <div aria-busy="true">
            <span className="skeleton" style={{ width: '55%', marginBottom: 8 }} />
            <span className="skeleton" style={{ width: '40%' }} />
          </div>
        )}
        {items !== null && zichtbaar.length === 0 && (
          <p className="hint">Geen meerwerk in deze status{projectFilter ? ' voor dit project' : ''}.</p>
        )}
        {zichtbaar.length > 0 && (
          <div className="tabel-scroll">
            <table>
              <tbody>
                <tr>
                  <th>Project</th>
                  <th>Omschrijving</th>
                  <th>Aantal</th>
                  <th>Gemeld door</th>
                  <th>In opdracht van</th>
                  <th>Status</th>
                  <th />
                </tr>
                {zichtbaar.map((item) => (
                  <tr key={item.id} className="clickable" onClick={() => setOpenItem(item)}>
                    <td>
                      <b>{item.project_naam ?? '?'}</b>
                    </td>
                    {/* Omschrijving ALTIJD voluit (mockup-norm): regelterugloop, nooit "…" */}
                    <td style={{ maxWidth: 380, whiteSpace: 'normal' }}>
                      {item.omschrijving}
                      <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 2 }}>
                        {item.heeft_foto ? 'foto ✓ · ' : 'geen foto · '}
                        {datumLabel(item.datum_uitgevoerd)}
                        {item.vraag_tekst && !item.vraag_antwoord && ' · vraag uitstaand'}
                        {item.vraag_antwoord && ' · vraag beantwoord'}
                      </div>
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {item.aantal} {eenheidLabel(item.eenheid)}
                    </td>
                    <td>{item.gemeld_door_naam ?? '—'}</td>
                    <td>
                      {item.in_opdracht_van ?? (
                        <span style={{ color: 'var(--warn)' }} title="Geen naam opgegeven">
                          — ⚠ geen naam
                        </span>
                      )}
                    </td>
                    <td>{statusBadge(item)}</td>
                    <td>›</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="hint" style={{ marginBottom: 0 }}>
          De wekelijkse doorbelastingscontrole op item-niveau gebruikt deze lijst als bron: goedgekeurd meerwerk
          dat na 2 weken nog niet op een verkoopfactuur staat, komt als signaal terug op de klantpagina.
        </p>
      </div>

      {openItem && (
        <MeerwerkPaneel
          administratieId={administratieId}
          item={openItem}
          onSluiten={() => setOpenItem(null)}
          onGewijzigd={(bijgewerkt, melding) => {
            setOpenItem(null)
            if (melding) meld(melding)
            setItems((huidig) => (huidig ?? []).map((i) => (i.id === bijgewerkt.id ? bijgewerkt : i)))
          }}
        />
      )}
    </div>
  )
}

/* --- beoordeel-zijpaneel (mockup .paneel) ------------------------------------------------------ */

function MeerwerkPaneel({
  administratieId,
  item,
  onSluiten,
  onGewijzigd,
}: {
  administratieId: string
  item: MeerwerkDto
  onSluiten: () => void
  onGewijzigd: (item: MeerwerkDto, melding?: string) => void
}) {
  const [toets, setToets] = useState<StaffelRegelDto[] | null>(null)
  const [fotoUrl, setFotoUrl] = useState<string | null>(null)
  const [prijs, setPrijs] = useState(item.prijs_per_eenheid ?? '')
  const [bedrag, setBedrag] = useState(item.bedrag ?? '')
  const [notitie, setNotitie] = useState(item.facturatie_notitie ?? '')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [dialoog, setDialoog] = useState<'afwijzen' | 'vraag' | 'doorbelast' | null>(null)

  useEffect(() => {
    haalContractToets(administratieId, item.id)
      .then((regels) => {
        setToets(regels)
        // Voorstel invullen (mens bevestigt of past aan) — alleen bij één regel en lege velden.
        if (regels.length === 1 && item.prijs_per_eenheid === null) {
          setPrijs(regels[0].prijs_per_eenheid)
          const voorstel = Number(regels[0].prijs_per_eenheid) * Number(item.aantal)
          setBedrag(voorstel.toFixed(2))
        }
      })
      .catch(() => setToets([]))
  }, [administratieId, item])

  // Foto via apiFetch (Authorization-header) → object-URL; een kale <img src> draagt geen token.
  useEffect(() => {
    if (!item.heeft_foto) return
    let url: string | null = null
    apiFetch(meerwerkFotoUrl(administratieId, item.id))
      .then(async (resp) => {
        if (!resp.ok) return
        const blob = await resp.blob()
        url = URL.createObjectURL(blob)
        setFotoUrl(url)
      })
      .catch(() => undefined)
    return () => {
      if (url) URL.revokeObjectURL(url)
    }
  }, [administratieId, item])

  async function actie(fn: () => Promise<MeerwerkDto>, melding: string) {
    setBezig(true)
    setFout(null)
    try {
      const bijgewerkt = await fn()
      onGewijzigd(bijgewerkt, melding)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Actie mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const isGemeld = item.status === 'gemeld'
  const kanGoedkeuren = isGemeld && prijs.trim() !== '' && bedrag.trim() !== ''

  return (
    <>
      <div className="zijpaneel-bg" onClick={() => !bezig && onSluiten()} />
      <div className="zijpaneel" role="dialog" aria-label="Meerwerk beoordelen">
        <div className="zijpaneel-kop">
          <h2>Meerwerk beoordelen</h2>
          {statusBadge(item)}
          <div style={{ marginLeft: 'auto' }}>
            <Button variant="ghost" maat="icoon" aria-label="Sluiten" onClick={onSluiten}>
              ✕
            </Button>
          </div>
        </div>
        <div className="zijpaneel-body">
          <div className="info-grid">
            <div className="rij">
              <span className="k">Project</span>
              <b>{item.project_naam ?? '?'}</b>
            </div>
            <div className="rij">
              <span className="k">Gemeld door</span>
              <b>{item.gemeld_door_naam ?? '—'} (uitvoerder)</b>
            </div>
            <div className="rij breed">
              <span className="k">Omschrijving</span>
              <b style={{ textAlign: 'right' }}>{item.omschrijving}</b>
            </div>
            <div className="rij">
              <span className="k">Datum uitgevoerd</span>
              <b>{new Date(item.datum_uitgevoerd).toLocaleDateString('nl-NL', { day: 'numeric', month: 'short', year: 'numeric' })}</b>
            </div>
            <div className="rij">
              <span className="k">Aantal</span>
              <b>
                {item.aantal} {eenheidLabel(item.eenheid)}
              </b>
            </div>
            <div className="rij">
              <span className="k">In opdracht van</span>
              <b>{item.in_opdracht_van ?? '— ⚠ geen naam'}</b>
            </div>
            {item.afwijs_reden && (
              <div className="rij breed">
                <span className="k">Afwijsreden</span>
                <b style={{ textAlign: 'right', color: 'var(--danger)' }}>{item.afwijs_reden}</b>
              </div>
            )}
          </div>

          {item.heeft_foto && (
            <div className="fotoblok">
              {fotoUrl ? <img src={fotoUrl} alt={item.foto_bestandsnaam ?? 'foto'} /> : `📷 ${item.foto_bestandsnaam ?? 'foto laden…'}`}
            </div>
          )}

          {toets !== null && toets.length > 0 && (
            <div className="prijsblok">
              <b>Contract-toets (offerte-staffel):</b>{' '}
              {toets.map((regel) => (
                <span key={regel.id}>
                  {regel.omschrijving} is {regel.verrekenbaar ? 'verrekenbaar' : 'níét verrekenbaar'}
                  {regel.bron ? ` (${regel.bron})` : ''} tegen € {regel.prijs_per_eenheid} /{eenheidLabel(regel.eenheid)}.{' '}
                </span>
              ))}
              Voorstel: <b>{item.aantal} {eenheidLabel(item.eenheid)} × € {toets[0].prijs_per_eenheid} = {euro((Number(toets[0].prijs_per_eenheid) * Number(item.aantal)).toFixed(2))}</b>{' '}
              — jij bevestigt of past aan, de app rekent nooit zelf door naar een boeking.
            </div>
          )}
          {toets !== null && toets.length === 0 && isGemeld && (
            <div className="prijsblok">
              <b>Contract-toets:</b> geen staffelregels bekend voor deze eenheid — prijs handmatig bepalen.
            </div>
          )}

          {isGemeld && (
            <div style={{ display: 'flex', gap: 10 }}>
              <FormField label="Verrekenprijs (per eenheid)" htmlFor="mw-prijs">
                <input id="mw-prijs" type="text" inputMode="decimal" value={prijs} onChange={(e) => setPrijs(e.target.value)} placeholder="9.20" />
              </FormField>
              <FormField label="Bedrag" htmlFor="mw-bedrag">
                <input id="mw-bedrag" type="text" inputMode="decimal" value={bedrag} onChange={(e) => setBedrag(e.target.value)} placeholder="772.80" />
              </FormField>
            </div>
          )}
          {isGemeld && (
            <FormField label="Notitie voor facturatie (optioneel)" htmlFor="mw-notitie">
              <input id="mw-notitie" type="text" value={notitie} onChange={(e) => setNotitie(e.target.value)} placeholder="bijv. meenemen op termijn 4" />
            </FormField>
          )}
          {!isGemeld && item.status !== 'afgewezen' && (
            <div className="info-grid" style={{ marginTop: 12 }}>
              <div className="rij">
                <span className="k">Bevestigde prijs</span>
                <b>€ {item.prijs_per_eenheid} /{eenheidLabel(item.eenheid)}</b>
              </div>
              <div className="rij">
                <span className="k">Bedrag</span>
                <b>{euro(item.bedrag)}</b>
              </div>
              {item.facturatie_notitie && (
                <div className="rij breed">
                  <span className="k">Facturatienotitie</span>
                  <b style={{ textAlign: 'right' }}>{item.facturatie_notitie}</b>
                </div>
              )}
            </div>
          )}

          {item.vraag_tekst && (
            <div className="prijsblok" style={{ background: 'var(--purple-bg)', color: 'var(--purple)' }}>
              <b>Vraag aan de uitvoerder:</b> {item.vraag_tekst}
              <br />
              {item.vraag_antwoord ? (
                <>
                  <b>Antwoord:</b> {item.vraag_antwoord}
                </>
              ) : (
                <i>nog niet beantwoord</i>
              )}
            </div>
          )}

          {isGemeld && (
            <p className="hint">
              Goedkeuren zet dit meerwerk in de bak "nog doorbelasten"; het item wordt bewaakt tot het op een
              verkoopfactuur staat. Afwijzen (eigen rekening) vergt een verplichte reden en blijft zichtbaar in
              de lijst.
            </p>
          )}
          {fout && <div className="fout">{fout}</div>}
        </div>
        <div className="zijpaneel-voet">
          {isGemeld && (
            <>
              <Button variant="gevaar" disabled={bezig} onClick={() => setDialoog('afwijzen')}>
                Afwijzen — eigen rekening…
              </Button>
              <div style={{ flex: 1 }} />
              <Button variant="secundair" disabled={bezig} onClick={() => setDialoog('vraag')}>
                Vraag aan uitvoerder
              </Button>
              <Button
                disabled={bezig || !kanGoedkeuren}
                onClick={() =>
                  void actie(
                    () =>
                      keurMeerwerkGoed(administratieId, item.id, {
                        prijs_per_eenheid: prijs.replace(',', '.'),
                        bedrag: bedrag.replace(',', '.'),
                        facturatie_notitie: notitie.trim() || null,
                      }),
                    'Meerwerk goedgekeurd voor doorbelasting — bewaakt tot het op een verkoopfactuur staat.',
                  )
                }
              >
                {bezig ? 'Bezig…' : 'Goedkeuren voor doorbelasting'}
              </Button>
            </>
          )}
          {item.status === 'goedgekeurd' && (
            <>
              <div style={{ flex: 1 }} />
              <Button disabled={bezig} onClick={() => setDialoog('doorbelast')}>
                Doorbelast markeren…
              </Button>
            </>
          )}
          {(item.status === 'doorbelast' || item.status === 'afgewezen') && (
            <>
              <div style={{ flex: 1 }} />
              <Button variant="secundair" onClick={onSluiten}>
                Sluiten
              </Button>
            </>
          )}
        </div>
      </div>

      {dialoog === 'afwijzen' && (
        <RedenDialog
          titel="Meerwerk afwijzen — eigen rekening"
          beschrijving={`De reden is verplicht en blijft zichtbaar in de lijst ("Afgewezen — eigen rekening").`}
          knop="Afwijzen"
          gevaar
          bezig={bezig}
          onSluiten={() => setDialoog(null)}
          onBevestigen={(reden) =>
            void actie(() => wijsMeerwerkAf(administratieId, item.id, reden), 'Meerwerk afgewezen (eigen rekening).')
          }
        />
      )}
      {dialoog === 'vraag' && (
        <RedenDialog
          titel="Vraag aan de uitvoerder"
          beschrijving="De vraag wordt zichtbaar bij de melding in de app; het antwoord komt hier terug. De status blijft 'gemeld'."
          knop="Vraag stellen"
          bezig={bezig}
          onSluiten={() => setDialoog(null)}
          onBevestigen={(tekst) =>
            void actie(() => stelMeerwerkVraag(administratieId, item.id, tekst), 'Vraag gesteld aan de uitvoerder.')
          }
        />
      )}
      {dialoog === 'doorbelast' && (
        <RedenDialog
          titel="Doorbelast markeren"
          beschrijving="Vul de verkoopfactuur-referentie in (bijv. VF-2608) — dit sluit de 2-weken-bewaking voor dit item."
          knop="Doorbelast markeren"
          placeholder="VF-…"
          bezig={bezig}
          onSluiten={() => setDialoog(null)}
          onBevestigen={(referentie) =>
            void actie(
              () => markeerDoorbelast(administratieId, item.id, referentie),
              'Gemarkeerd als doorbelast.',
            )
          }
        />
      )}
    </>
  )
}

function RedenDialog({
  titel,
  beschrijving,
  knop,
  placeholder,
  gevaar,
  bezig,
  onSluiten,
  onBevestigen,
}: {
  titel: string
  beschrijving: string
  knop: string
  placeholder?: string
  gevaar?: boolean
  bezig: boolean
  onSluiten: () => void
  onBevestigen: (tekst: string) => void
}) {
  const [tekst, setTekst] = useState('')
  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>{titel}</DialogTitle>
        <DialogDescription>{beschrijving}</DialogDescription>
        <textarea
          rows={3}
          value={tekst}
          onChange={(e) => setTekst(e.target.value)}
          placeholder={placeholder}
          style={{ width: '100%' }}
        />
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button
            variant={gevaar ? 'gevaar' : 'primair'}
            disabled={bezig || tekst.trim() === ''}
            onClick={() => onBevestigen(tekst.trim())}
          >
            {bezig ? 'Bezig…' : knop}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
