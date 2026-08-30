// Voorraad-aansluiting — controle-laag (bouwrun 28-08 blok D, mockup voorraad-aansluiting.html §1/§2 =
// bouwnorm, stijl designpass v2). Per administratie mét de opt-in "Voorraad bijhouden": per
// artikelgroep Begin + Inkoop (facturen) − Verkoop (facturen) = Theoretisch vs Systeemstand
// (telling per datum) → Verschil + Signaal (tolerantie per groep, default 1%). Bron per kolom
// zichtbaar; drill-down naar factuurregels (in én uit) + dagstanden; de teller "Niet
// genormaliseerd" bewust prominent. Normalisatie is volautomatisch — corrigeren kán (herrekent
// historie), maar is nooit een voorwaarde. Puur MI: nooit een boeking.
// v2 (30-08, besluiten Peter 29-08): dienst-/transportregels blijven bewaard mét soort-label (tellen niet) —
// §3 inzage "als dienst geclassificeerd" per tekst mét aantallen + correctie dienst ↔ artikel; §4 codes-
// inzage (artikelcode → groep per richting, AI-voorstel vs handmatig) + correctie. Nooit blind vertrouwen.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { FoutMelding } from '../ui/FoutMelding'
import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField, Select, SkeletonRegels } from '../ui/basis'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import {
  aantal,
  bronLabel,
  classificatieBronLabel,
  corrigeerArtikelcode,
  corrigeerNormalisatie,
  haalAansluiting,
  haalArtikelcodes,
  haalArtikelgroepen,
  haalDagstanden,
  haalDienstTeksten,
  haalVoorraadRegels,
  herrekenVoorraad,
  maakArtikelgroep,
  signaalTekst,
  SOORT_LABEL,
  voerTellingIn,
  zetTolerantie,
  type AansluitingDto,
  type ArtikelcodeDto,
  type ArtikelgroepDto,
  type DagStandDto,
  type DienstTekstDto,
  type GroepAansluitingDto,
  type VoorraadRegelDto,
  type VoorraadSoort,
} from './voorraadApi'

function isoVandaag(): string {
  return new Date().toISOString().slice(0, 10)
}

function isoJaarStart(): string {
  return `${new Date().getFullYear()}-01-01`
}

const STATUS_LABEL: Record<VoorraadRegelDto['normalisatie_status'], string> = {
  genormaliseerd: 'zeker',
  onzeker: 'onzeker — telt mee mét vlag',
  uitgesloten: 'dienst (vóór v2 — hernormaliseren)',
  niet_genormaliseerd: 'niet genormaliseerd',
}

/** Keuze uit de correctie-select → soort + groep (v2: geen 'uitsluiten' meer, wél dienst/transport). */
function keuzeNaarCorrectie(keuze: string): { soort: VoorraadSoort; artikelgroep_id: string | null } {
  if (keuze === '__dienst__') return { soort: 'dienst', artikelgroep_id: null }
  if (keuze === '__transport__') return { soort: 'transport', artikelgroep_id: null }
  return { soort: 'artikel', artikelgroep_id: keuze }
}

export function VoorraadScreen() {
  const { administraties } = useAdministraties()
  const [zoekParams, setZoekParams] = useSearchParams()
  const administratieId = zoekParams.get('administratie') ?? ''
  const [van, setVan] = useState(zoekParams.get('van') ?? isoJaarStart())
  const [tot, setTot] = useState(zoekParams.get('tot') ?? isoVandaag())
  const [data, setData] = useState<AansluitingDto | null>(null)
  const [groepen, setGroepen] = useState<ArtikelgroepDto[]>([])
  const [fout, setFout] = useState<string | null>(null)
  const [uit, setUit] = useState(false)
  const [laden, setLaden] = useState(false)
  const [versie, setVersie] = useState(0)
  const [melding, setMelding] = useState<string | null>(null)
  const [detail, setDetail] = useState<{ groep: GroepAansluitingDto; regels: VoorraadRegelDto[]; dagen: DagStandDto[] } | null>(null)
  const [normalisatieOpen, setNormalisatieOpen] = useState(false)
  const [normRegels, setNormRegels] = useState<VoorraadRegelDto[] | null>(null)
  // v2 §3/§4: dienst-inzage en codes-inzage (controlemechanisme).
  const [dienstOpen, setDienstOpen] = useState(false)
  const [dienstTeksten, setDienstTeksten] = useState<DienstTekstDto[] | null>(null)
  const [codesOpen, setCodesOpen] = useState(false)
  const [codes, setCodes] = useState<ArtikelcodeDto[] | null>(null)
  const [tellingVoor, setTellingVoor] = useState<{ groep: GroepAansluitingDto; datum: string; aantal: string } | null>(null)
  // Blok B (nazorg bouwrun blok D): invoer via designpass-v2-dialogen i.p.v. window.prompt.
  const [groepDialoog, setGroepDialoog] = useState<{ regel: VoorraadRegelDto; naam: string; eenheid: string; tolerantie: string } | null>(null)
  const [tolerantieDialoog, setTolerantieDialoog] = useState<{ groep: GroepAansluitingDto; waarde: string } | null>(null)
  const [dialoogBezig, setDialoogBezig] = useState(false)
  const [dialoogFout, setDialoogFout] = useState<string | null>(null)

  const kies = (id: string) => {
    const p = new URLSearchParams(zoekParams)
    p.set('administratie', id)
    setZoekParams(p, { replace: true })
    setDetail(null)
    setNormalisatieOpen(false)
    setDienstOpen(false)
    setCodesOpen(false)
  }

  const laad = useCallback(() => {
    if (!administratieId) return
    setLaden(true)
    setFout(null)
    setUit(false)
    Promise.all([haalAansluiting(administratieId, van, tot), haalArtikelgroepen(administratieId)])
      .then(([a, g]) => {
        setData(a)
        setGroepen(g)
      })
      .catch((err: unknown) => {
        setData(null)
        if (err instanceof ApiError && err.status === 409) setUit(true)
        else setFout(err instanceof Error ? err.message : 'Laden mislukt.')
      })
      .finally(() => setLaden(false))
  }, [administratieId, van, tot])

  useEffect(() => {
    laad()
  }, [laad, versie])

  const verversen = async () => {
    if (!administratieId) return
    setMelding(null)
    setLaden(true)
    try {
      const r = await herrekenVoorraad(administratieId)
      setMelding(
        `Herrekend: ${r.inkoop_regels} inkoopregels uit ${r.inkoop_documenten} facturen, ${r.verkoop_regels} verkoopregels uit ${r.verkoop_documenten} facturen, ${r.rlz_regels} RLZ-verkoopregels.`,
      )
      setVersie((v) => v + 1)
      if (dienstOpen) void openDienstInzage()
      if (codesOpen) void openCodesInzage()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Verversen mislukt.')
      setLaden(false)
    }
  }

  const openDetail = async (groep: GroepAansluitingDto) => {
    setDetail(null)
    const [regels, dagen] = await Promise.all([
      haalVoorraadRegels(administratieId, van, tot, { artikelgroepId: groep.artikelgroep_id }),
      haalDagstanden(administratieId, groep.artikelgroep_id, van, tot),
    ])
    setDetail({ groep, regels, dagen })
  }

  const openNormalisatie = async () => {
    setNormalisatieOpen(true)
    setNormRegels(null)
    const [niet, onzeker] = await Promise.all([
      haalVoorraadRegels(administratieId, van, tot, { status: 'niet_genormaliseerd' }),
      haalVoorraadRegels(administratieId, van, tot, { status: 'onzeker' }),
    ])
    setNormRegels([...niet, ...onzeker])
  }

  const openDienstInzage = async () => {
    setDienstOpen(true)
    setDienstTeksten(null)
    try {
      setDienstTeksten(await haalDienstTeksten(administratieId, van, tot))
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Dienst-inzage laden mislukt.')
    }
  }

  const openCodesInzage = async () => {
    setCodesOpen(true)
    setCodes(null)
    try {
      setCodes(await haalArtikelcodes(administratieId))
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Codes-inzage laden mislukt.')
    }
  }

  const naCorrectie = (herrekend: number, wat: string) => {
    setMelding(`Correctie toegepast op ${herrekend} regel${herrekend === 1 ? '' : 's'} ${wat} (historie herrekend).`)
    setVersie((v) => v + 1)
    if (normalisatieOpen) void openNormalisatie()
    if (dienstOpen) void openDienstInzage()
    if (codesOpen) void openCodesInzage()
  }

  const corrigeer = async (regel: Pick<VoorraadRegelDto, 'id' | 'artikeltekst' | 'eenheid'>, keuze: string) => {
    setMelding(null)
    if (keuze === '__nieuw__') {
      setDialoogFout(null)
      setGroepDialoog({ regel: regel as VoorraadRegelDto, naam: '', eenheid: regel.eenheid ?? 'st', tolerantie: '1.00' })
      return
    }
    try {
      const r = await corrigeerNormalisatie(administratieId, { regel_id: regel.id, ...keuzeNaarCorrectie(keuze) })
      naCorrectie(r.herrekend, 'met dezelfde leverancier + artikeltekst/artikelcode')
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Corrigeren mislukt.')
    }
  }

  const corrigeerCode = async (koppeling: ArtikelcodeDto, keuze: string) => {
    setMelding(null)
    try {
      const r = await corrigeerArtikelcode(administratieId, koppeling.id, keuzeNaarCorrectie(keuze))
      naCorrectie(r.herrekend, `met code ${koppeling.code} (${koppeling.richting === 'in' ? 'inkoop' : 'verkoop'})`)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Code corrigeren mislukt.')
    }
  }

  const nieuweGroepOpslaan = async () => {
    if (!groepDialoog) return
    const naam = groepDialoog.naam.trim()
    if (!naam) {
      setDialoogFout('Geef de artikelgroep een naam.')
      return
    }
    setDialoogBezig(true)
    setDialoogFout(null)
    try {
      const g = await maakArtikelgroep(administratieId, naam, groepDialoog.eenheid.trim() || 'st', groepDialoog.tolerantie.replace(',', '.') || '1.00')
      const r = await corrigeerNormalisatie(administratieId, { regel_id: groepDialoog.regel.id, soort: 'artikel', artikelgroep_id: g.id })
      setGroepDialoog(null)
      naCorrectie(r.herrekend, `— artikelgroep "${g.naam}" aangemaakt`)
    } catch (err) {
      setDialoogFout(err instanceof ApiError ? err.message : 'Artikelgroep aanmaken mislukt.')
    } finally {
      setDialoogBezig(false)
    }
  }

  const tellingOpslaan = async () => {
    if (!tellingVoor) return
    try {
      await voerTellingIn(administratieId, {
        artikelgroep_id: tellingVoor.groep.artikelgroep_id,
        datum: tellingVoor.datum,
        aantal: tellingVoor.aantal.replace(',', '.'),
        opmerking: null,
      })
      setTellingVoor(null)
      setMelding(`Telling voor ${tellingVoor.groep.naam} per ${tellingVoor.datum} opgeslagen.`)
      setVersie((v) => v + 1)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Telling opslaan mislukt.')
    }
  }

  const tolerantieWijzigen = (groep: GroepAansluitingDto) => {
    setDialoogFout(null)
    setTolerantieDialoog({ groep, waarde: aantal(groep.tolerantie_pct, 2) })
  }

  const tolerantieOpslaan = async () => {
    if (!tolerantieDialoog) return
    const waarde = tolerantieDialoog.waarde.trim().replace(',', '.')
    const n = Number(waarde)
    if (waarde === '' || Number.isNaN(n) || n < 0 || n > 100) {
      setDialoogFout('Tolerantie moet een percentage tussen 0 en 100 zijn.')
      return
    }
    setDialoogBezig(true)
    setDialoogFout(null)
    try {
      await zetTolerantie(administratieId, tolerantieDialoog.groep.artikelgroep_id, waarde)
      setTolerantieDialoog(null)
      setMelding(`Tolerantie voor ${tolerantieDialoog.groep.naam} gezet op ${aantal(waarde, 2)}%.`)
      setVersie((v) => v + 1)
    } catch (err) {
      setDialoogFout(err instanceof ApiError ? err.message : 'Tolerantie wijzigen mislukt.')
    } finally {
      setDialoogBezig(false)
    }
  }

  const groepOpties = useMemo(() => groepen.filter((g) => g.actief), [groepen])
  const nietGenormaliseerd = (data?.niet_genormaliseerd_in ?? 0) + (data?.niet_genormaliseerd_uit ?? 0)
  const dienstTotaal = (data?.dienst_regels ?? 0) + (data?.transport_regels ?? 0)

  /** Correctie-select (v2): artikelgroepen, nieuwe groep, dienst, transport — één component voor §2/§3/§4. */
  const CorrectieSelect = ({ label, huidige, onKeuze }: { label: string; huidige?: string; onKeuze: (keuze: string) => void }) => (
    <Select
      aria-label={label}
      value=""
      onChange={(e) => {
        if (e.target.value) onKeuze(e.target.value)
      }}
    >
      <option value="">{huidige ? `— nu: ${huidige} — corrigeer naar… —` : '— corrigeer naar… —'}</option>
      {groepOpties.map((g) => (
        <option key={g.id} value={g.id}>
          artikel: {g.naam}
        </option>
      ))}
      <option value="__nieuw__">+ nieuwe artikelgroep…</option>
      <option value="__dienst__">dienst (geen voorraad, wél omzet-/dienstregel)</option>
      <option value="__transport__">transport (geen voorraad)</option>
    </Select>
  )

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 style={{ margin: 0 }}>Voorraad-aansluiting</h1>
          <div className="hint" style={{ marginTop: 2 }}>
            Onafhankelijke controle-laag: instroom uit gescande inkoopfacturen (extern) vs uitstroom uit verkoopfactuurregels
            (intern) — theoretische stand tegenover de systeemstand. Puur signaal, nooit een boeking.
          </div>
        </div>
      </div>

      <div className="panel" style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div style={{ minWidth: 280 }}>
          <AdministratieCombobox
            label="Administratie"
            administraties={administraties ?? []}
            waarde={administratieId || null}
            onWijzig={kies}
            placeholder="— kies administratie —"
          />
        </div>
        <label style={{ margin: 0, fontSize: 12 }}>
          Periode van
          <input type="date" value={van} onChange={(e) => setVan(e.target.value)} aria-label="Periode van" />
        </label>
        <label style={{ margin: 0, fontSize: 12 }}>
          tot en met
          <input type="date" value={tot} onChange={(e) => setTot(e.target.value)} aria-label="Periode tot" />
        </label>
        <Button variant="secundair" maat="klein" disabled={!administratieId || laden} onClick={() => void verversen()}>
          ⟳ Verversen
        </Button>
      </div>

      {fout && <FoutMelding melding="Er ging iets mis." detail={fout} onOpnieuw={() => setVersie((v) => v + 1)} />}
      {melding && (
        <div className="hint" role="status" style={{ marginBottom: 10 }}>
          {melding}
        </div>
      )}

      {!administratieId && <p className="hint">Kies een administratie met de opt-in &ldquo;Voorraad bijhouden&rdquo;.</p>}
      {uit && (
        <div className="panel" data-testid="voorraad-uit">
          <b>Voorraad bijhouden staat uit voor deze administratie.</b>
          <p className="hint" style={{ marginBottom: 0 }}>
            Een Beheerder zet de opt-in aan op <Link to="/instellingen/administraties">Instellingen › Administraties</Link>{' '}
            (kolom &ldquo;Voorraad bijhouden&rdquo;). Daarna bouwt &ldquo;⟳ Verversen&rdquo; de feitenlaag op uit de bestaande facturen.
          </p>
        </div>
      )}
      {administratieId && laden && data === null && !uit && <SkeletonRegels />}

      {data !== null && !uit && (
        <>
          <div className="panel">
            <div className="tabel-scroll">
              <table data-testid="aansluiting-tabel">
                <thead>
                  <tr>
                    <th>Artikelgroep</th>
                    <th className="amount" title={`Stand vóór ${data.van}: Σ inkoop − Σ verkoop`}>Begin</th>
                    <th className="amount" title={data.bronnen.inkoop}>+ Inkoop (facturen)</th>
                    <th className="amount" title={data.bronnen.verkoop}>− Verkoop (facturen)</th>
                    <th className="amount">= Theoretisch</th>
                    <th className="amount" title={data.bronnen.systeemstand}>Systeemstand</th>
                    <th className="amount">Verschil</th>
                    <th>Signaal</th>
                    <th className="acties" />
                  </tr>
                </thead>
                <tbody>
                  {data.groepen.map((g) => {
                    const s = signaalTekst(g)
                    return (
                      <tr key={g.artikelgroep_id}>
                        <td>
                          <button type="button" className="linkbtn" onClick={() => void openDetail(g)}>
                            <b>{g.naam}</b>
                          </button>
                          <div className="hint" style={{ fontSize: 11 }}>
                            {g.eenheid} · tolerantie {aantal(g.tolerantie_pct, 2)}%
                            {Number(g.onzeker_pct) > 0 && ` · ${aantal(g.onzeker_pct, 0)}% onzeker genormaliseerd`}
                          </div>
                        </td>
                        <td className="amount">{aantal(g.begin)}</td>
                        <td className="amount">{aantal(g.inkoop)}</td>
                        <td className="amount">{aantal(g.verkoop)}</td>
                        <td className="amount">
                          <b>{aantal(g.theoretisch)}</b>
                        </td>
                        <td className="amount">
                          {g.systeemstand !== null ? (
                            <>
                              {aantal(g.systeemstand)}
                              <div className="hint" style={{ fontSize: 11 }}>telling {g.telling_datum}</div>
                            </>
                          ) : (
                            '—'
                          )}
                        </td>
                        <td className="amount">{g.verschil !== null ? (Number(g.verschil) > 0 ? '+' : '') + aantal(g.verschil) : '—'}</td>
                        <td>
                          <Badge variant={s.soort === 'ok' ? 'ok' : s.soort === 'vlag' ? 'warn' : 'stil'}>
                            {s.soort === 'ok' ? '✓ ' : s.soort === 'vlag' ? '⚑ ' : ''}
                            {s.tekst}
                          </Badge>
                          {s.soort === 'vlag' && Number(g.onzeker_pct) > 0 && (
                            <div className="hint" style={{ fontSize: 11 }}>
                              {aantal(g.onzeker_pct, 0)}% van de regels is onzeker genormaliseerd — eerst normaliseren
                            </div>
                          )}
                        </td>
                        <td className="acties" style={{ whiteSpace: 'nowrap' }}>
                          <Button
                            variant="secundair"
                            maat="klein"
                            onClick={() => setTellingVoor({ groep: g, datum: isoVandaag(), aantal: '' })}
                          >
                            Telling…
                          </Button>{' '}
                          <Button variant="ghost" maat="klein" onClick={() => tolerantieWijzigen(g)}>
                            Tolerantie
                          </Button>
                        </td>
                      </tr>
                    )
                  })}
                  <tr data-testid="niet-genormaliseerd-rij">
                    <td>
                      <b>Niet genormaliseerd</b>
                      <div className="hint" style={{ fontSize: 11 }}>
                        de aansluiting is pas dekkend als dit ↓ 0 nadert
                      </div>
                    </td>
                    <td className="amount">—</td>
                    <td className="amount">{data.niet_genormaliseerd_in} regels</td>
                    <td className="amount">{data.niet_genormaliseerd_uit} regels</td>
                    <td className="amount">—</td>
                    <td className="amount">—</td>
                    <td className="amount">—</td>
                    <td>
                      {nietGenormaliseerd > 0 || data.onzeker_totaal > 0 ? (
                        <Button variant="secundair" maat="klein" onClick={() => void openNormalisatie()}>
                          → normaliseren ({nietGenormaliseerd} + {data.onzeker_totaal} onzeker)
                        </Button>
                      ) : (
                        <Badge variant="ok">✓ alles genormaliseerd</Badge>
                      )}
                    </td>
                    <td />
                  </tr>
                  <tr data-testid="diensten-rij">
                    <td>
                      <b>Diensten &amp; transport</b>
                      <div className="hint" style={{ fontSize: 11 }}>
                        soort-label: tellen niet in de voorraad, blijven bewaard als omzet-/dienstregel (km&rsquo;s, keuringen, werktijd)
                      </div>
                    </td>
                    <td className="amount">—</td>
                    <td className="amount" colSpan={2}>
                      {data.dienst_regels} dienst · {data.transport_regels} transport
                    </td>
                    <td className="amount">—</td>
                    <td className="amount">—</td>
                    <td className="amount">—</td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <Button variant="secundair" maat="klein" onClick={() => void openDienstInzage()} disabled={dienstTotaal === 0}>
                        → als dienst geclassificeerd ({dienstTotaal})
                      </Button>{' '}
                      <Button variant="ghost" maat="klein" onClick={() => void openCodesInzage()}>
                        artikelcodes
                      </Button>
                    </td>
                    <td />
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="hint" style={{ marginBottom: 0 }}>
              {data.regels_totaal} factuurregels in de periode · mutaties op dagniveau · bron per kolom: inkoop = {data.bronnen.inkoop},
              verkoop = {data.bronnen.verkoop}, systeemstand = {data.bronnen.systeemstand}
              {data.bronnen.diensten ? `; diensten = ${data.bronnen.diensten}` : ''}.
            </p>
          </div>

          {tellingVoor && (
            <div className="panel" data-testid="telling-invoer" style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <b>Telling — {tellingVoor.groep.naam}</b>
              <label style={{ margin: 0, fontSize: 12 }}>
                Datum
                <input type="date" value={tellingVoor.datum} onChange={(e) => setTellingVoor({ ...tellingVoor, datum: e.target.value })} aria-label="Telling datum" />
              </label>
              <label style={{ margin: 0, fontSize: 12 }}>
                Aantal ({tellingVoor.groep.eenheid})
                <input inputMode="decimal" value={tellingVoor.aantal} onChange={(e) => setTellingVoor({ ...tellingVoor, aantal: e.target.value })} aria-label="Telling aantal" />
              </label>
              <Button maat="klein" disabled={!tellingVoor.aantal} onClick={() => void tellingOpslaan()}>
                Telling opslaan
              </Button>
              <Button variant="ghost" maat="klein" onClick={() => setTellingVoor(null)}>
                Annuleren
              </Button>
            </div>
          )}

          {detail && (
            <div className="panel" data-testid="groep-detail">
              <h2 style={{ marginTop: 0 }}>
                {detail.groep.naam} — factuurregels {data.van} t/m {data.tot}
              </h2>
              <div className="tabel-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Datum</th>
                      <th>Richting</th>
                      <th>Relatie</th>
                      <th>Factuurregel</th>
                      <th className="amount">Aantal</th>
                      <th className="amount">Prijs</th>
                      <th>Zekerheid</th>
                      <th>Bron</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.regels.map((r) => (
                      <tr key={r.id}>
                        <td>{r.datum}</td>
                        <td>{r.richting === 'in' ? 'in (inkoop)' : 'uit (verkoop)'}</td>
                        <td>{r.relatie_naam ?? '—'}</td>
                        <td>&ldquo;{r.artikeltekst}&rdquo;</td>
                        <td className="amount">{aantal(r.aantal, 3)} {r.eenheid ?? ''}</td>
                        <td className="amount">{r.prijs !== null ? `€ ${aantal(r.prijs, 2)}` : '—'}</td>
                        <td>
                          <Badge variant={r.normalisatie_status === 'onzeker' ? 'warn' : 'ok'}>
                            {r.normalisatie_status === 'onzeker' ? '⚑' : '✓'} {aantal(r.normalisatie_zekerheid !== null ? String(Number(r.normalisatie_zekerheid) * 100) : null, 0)}%
                          </Badge>
                        </td>
                        <td>
                          {r.document_id ? (
                            <Link to={`/documenten/${administratieId}/${r.document_id}`}>{bronLabel(r)} →</Link>
                          ) : (
                            <span className="hint" title="Gelezen uit RLZ (dagelijkse leesroute, alleen geboekte facturen) — geen app-document">
                              {bronLabel(r)}
                            </span>
                          )}
                          {r.artikelcode && (
                            <div className="hint" style={{ fontSize: 11 }} title="artikelcode uit de regel — deterministische normalisatiesleutel">
                              code {r.artikelcode}
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <h3>Dagstanden</h3>
              <div className="tabel-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Dag</th>
                      <th className="amount">+ in</th>
                      <th className="amount">− uit</th>
                      <th className="amount">Stand</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.dagen.map((d) => (
                      <tr key={d.datum}>
                        <td>{d.datum}</td>
                        <td className="amount">{aantal(d.inkoop)}</td>
                        <td className="amount">{aantal(d.verkoop)}</td>
                        <td className="amount">{aantal(d.stand)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {normalisatieOpen && (
            <div className="panel" data-testid="normalisatie-paneel">
              <h2 style={{ marginTop: 0 }}>Catalogus-normalisatie — volautomatisch, mét zichtbare onzekerheid</h2>
              <p className="hint">
                Er hoeft níéts bevestigd te worden: onzekere matches tellen mee mét vlag. Corrigeren kán (optioneel) en geldt
                vanaf dan voor álle regels met dezelfde leverancier + artikeltekst — historie wordt herrekend.
              </p>
              {normRegels === null && <SkeletonRegels />}
              {normRegels !== null && normRegels.length === 0 && <p className="hint">Alles is genormaliseerd.</p>}
              {normRegels !== null && normRegels.length > 0 && (
                <div className="tabel-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Factuurregel (leverancier)</th>
                        <th className="amount">Aantal · eenheid</th>
                        <th>Genormaliseerd als</th>
                        <th>Zekerheid</th>
                        <th>Corrigeer</th>
                      </tr>
                    </thead>
                    <tbody>
                      {normRegels.map((r) => (
                        <tr key={r.id}>
                          <td>
                            &ldquo;{r.artikeltekst}&rdquo; — {r.relatie_naam ?? 'onbekend'}
                          </td>
                          <td className="amount">{aantal(r.aantal, 3)} {r.eenheid ?? ''}</td>
                          <td>
                            {r.artikelgroep_naam ?? <span className="hint">—</span>}
                            {r.artikelcode && <div className="hint" style={{ fontSize: 11 }}>code {r.artikelcode}</div>}
                          </td>
                          <td>
                            <Badge variant={r.normalisatie_status === 'niet_genormaliseerd' ? 'danger' : 'warn'}>
                              {STATUS_LABEL[r.normalisatie_status]}
                              {r.normalisatie_zekerheid !== null && ` (${aantal(String(Number(r.normalisatie_zekerheid) * 100), 0)}%)`}
                            </Badge>
                          </td>
                          <td>
                            <CorrectieSelect label={`Corrigeer ${r.artikeltekst}`} onKeuze={(keuze) => void corrigeer(r, keuze)} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {dienstOpen && (
            <div className="panel" data-testid="dienst-inzage">
              <h2 style={{ marginTop: 0 }}>Als dienst geclassificeerd — controle op de regex/AI</h2>
              <p className="hint">
                Elke unieke tekst die níét in de voorraad telt, mét aantallen en de bron van de classificatie. Klopt het niet
                (bv. een huur-regel die wél een artikel is): corrigeer — geldt voor álle regels met dezelfde leverancier + tekst
                (en dezelfde artikelcode), historie herrekend. De regels zelf blijven bewaard als omzet-/dienstinformatie.
              </p>
              {dienstTeksten === null && <SkeletonRegels />}
              {dienstTeksten !== null && dienstTeksten.length === 0 && <p className="hint">Geen dienst-/transportregels in deze periode.</p>}
              {dienstTeksten !== null && dienstTeksten.length > 0 && (
                <div className="tabel-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Tekst (relatie)</th>
                        <th>Soort</th>
                        <th>Bron</th>
                        <th className="amount">Regels</th>
                        <th className="amount">Σ aantal</th>
                        <th className="amount">Σ netto</th>
                        <th>Corrigeer</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dienstTeksten.map((d) => (
                        <tr key={`${d.vendor_id ?? '-'}|${d.artikeltekst_norm}`}>
                          <td>
                            &ldquo;{d.artikeltekst}&rdquo;
                            <div className="hint" style={{ fontSize: 11 }}>
                              {d.relatie_naam ?? 'eigen verkoop'} · {d.richtingen === 'in' ? 'inkoop' : d.richtingen === 'uit' ? 'verkoop' : 'in + uit'}
                            </div>
                          </td>
                          <td>
                            <Badge variant="stil">{SOORT_LABEL[d.soort]}</Badge>
                          </td>
                          <td>
                            <Badge variant={d.bron === 'handmatig' ? 'ok' : d.bron === 'legacy' ? 'warn' : 'stil'}>{classificatieBronLabel(d.bron)}</Badge>
                          </td>
                          <td className="amount">{d.regels}</td>
                          <td className="amount">{aantal(d.som_aantal, 3)}</td>
                          <td className="amount">€ {aantal(d.som_netto, 2)}</td>
                          <td>
                            <CorrectieSelect
                              label={`Corrigeer dienst ${d.artikeltekst}`}
                              huidige={SOORT_LABEL[d.soort]}
                              onKeuze={(keuze) => void corrigeer({ id: d.voorbeeld_regel_id, artikeltekst: d.artikeltekst, eenheid: null }, keuze)}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {codesOpen && (
            <div className="panel" data-testid="codes-inzage">
              <h2 style={{ marginTop: 0 }}>Artikelcodes — deterministische sleutel per richting</h2>
              <p className="hint">
                Inkoopcodes (leverancier) en verkoopcodes (eigen omschrijving, bv. &ldquo;(560140.4)&rdquo;) zijn verschillende
                sleutels — nooit gelijkgesteld. Eerste keer per code = AI-voorstel (zichtbaar mét zekerheid), daarna deterministisch
                vóór de tekstregel en vóór de AI. Corrigeren geldt voor álle regels met die code (historie herrekend).
              </p>
              {codes === null && <SkeletonRegels />}
              {codes !== null && codes.length === 0 && <p className="hint">Nog geen artikelcodes gekoppeld.</p>}
              {codes !== null && codes.length > 0 && (
                <div className="tabel-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Code</th>
                        <th>Richting · relatie</th>
                        <th>Voorbeeldtekst</th>
                        <th>Gekoppeld aan</th>
                        <th>Bron · zekerheid</th>
                        <th className="amount">Regels · teksten</th>
                        <th>Corrigeer</th>
                      </tr>
                    </thead>
                    <tbody>
                      {codes.map((k) => (
                        <tr key={k.id}>
                          <td>
                            <b>{k.code}</b>
                          </td>
                          <td>
                            {k.richting === 'in' ? 'inkoop' : 'verkoop'} · {k.relatie_naam ?? 'eigen verkoop'}
                          </td>
                          <td className="hint">{k.voorbeeld_tekst ?? '—'}</td>
                          <td>{k.soort === 'artikel' ? (k.artikelgroep_naam ?? '—') : <Badge variant="stil">{SOORT_LABEL[k.soort]}</Badge>}</td>
                          <td>
                            <Badge variant={k.bron === 'handmatig' ? 'ok' : Number(k.zekerheid) < 0.75 ? 'warn' : 'stil'}>
                              {classificatieBronLabel(k.bron)}
                              {k.zekerheid !== null && k.bron !== 'handmatig' && ` (${aantal(String(Number(k.zekerheid) * 100), 0)}%)`}
                            </Badge>
                          </td>
                          <td className="amount">
                            {k.regels} · {k.teksten}
                          </td>
                          <td>
                            <CorrectieSelect
                              label={`Corrigeer code ${k.code}`}
                              huidige={k.soort === 'artikel' ? (k.artikelgroep_naam ?? undefined) : SOORT_LABEL[k.soort]}
                              onKeuze={(keuze) => {
                                if (keuze === '__nieuw__') {
                                  setFout('Maak de artikelgroep eerst aan via het normalisatie-paneel (+ nieuwe artikelgroep…) en kies die dan hier.')
                                  return
                                }
                                void corrigeerCode(k, keuze)
                              }}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* Blok B: nieuwe artikelgroep vanuit de normalisatie-correctie — dialoog i.p.v. window.prompt. */}
      <Dialog open={groepDialoog !== null} onOpenChange={(open) => !open && !dialoogBezig && setGroepDialoog(null)}>
        <DialogContent aria-describedby={undefined} data-testid="nieuwe-groep-dialoog">
          <DialogTitle>Nieuwe artikelgroep</DialogTitle>
          <DialogDescription>
            {groepDialoog && (
              <>
                Voor &ldquo;{groepDialoog.regel.artikeltekst}&rdquo;. De correctie geldt daarna voor álle regels met dezelfde leverancier +
                artikeltekst (historie herrekend).
              </>
            )}
          </DialogDescription>
          {groepDialoog && (
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void nieuweGroepOpslaan()
              }}
            >
              <FormField label="Naam" htmlFor="groep-naam">
                <input
                  id="groep-naam"
                  autoFocus
                  maxLength={80}
                  value={groepDialoog.naam}
                  onChange={(e) => setGroepDialoog({ ...groepDialoog, naam: e.target.value })}
                  placeholder="bv. Koppelingen 48mm"
                />
              </FormField>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <FormField label="Eenheid" htmlFor="groep-eenheid">
                  <input id="groep-eenheid" maxLength={16} value={groepDialoog.eenheid} onChange={(e) => setGroepDialoog({ ...groepDialoog, eenheid: e.target.value })} />
                </FormField>
                <FormField label="Tolerantie (%)" htmlFor="groep-tolerantie" hint="default 1%">
                  <input id="groep-tolerantie" inputMode="decimal" value={groepDialoog.tolerantie} onChange={(e) => setGroepDialoog({ ...groepDialoog, tolerantie: e.target.value })} />
                </FormField>
              </div>
              {dialoogFout && <div className="fout">{dialoogFout}</div>}
              <DialogFooter>
                <Button type="button" variant="ghost" onClick={() => setGroepDialoog(null)} disabled={dialoogBezig}>
                  Annuleren
                </Button>
                <Button type="submit" disabled={dialoogBezig}>
                  {dialoogBezig ? 'Bezig…' : 'Aanmaken en corrigeren'}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>

      {/* Blok B: tolerantie per artikelgroep — dialoog i.p.v. window.prompt. */}
      <Dialog open={tolerantieDialoog !== null} onOpenChange={(open) => !open && !dialoogBezig && setTolerantieDialoog(null)}>
        <DialogContent aria-describedby={undefined} data-testid="tolerantie-dialoog">
          <DialogTitle>Tolerantie — {tolerantieDialoog?.groep.naam}</DialogTitle>
          <DialogDescription>
            Verschil tussen theoretische stand en systeemstand binnen dit percentage = &ldquo;binnen tolerantie&rdquo;; daarboven het signaal
            &ldquo;onderzoeken&rdquo;. Alleen presentatie van het signaal — nooit een boeking.
          </DialogDescription>
          {tolerantieDialoog && (
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void tolerantieOpslaan()
              }}
            >
              <FormField label="Tolerantie (%)" htmlFor="tolerantie-pct" hint="0 t/m 100, decimalen met komma of punt">
                <input
                  id="tolerantie-pct"
                  autoFocus
                  inputMode="decimal"
                  value={tolerantieDialoog.waarde}
                  onChange={(e) => setTolerantieDialoog({ ...tolerantieDialoog, waarde: e.target.value })}
                />
              </FormField>
              {dialoogFout && <div className="fout">{dialoogFout}</div>}
              <DialogFooter>
                <Button type="button" variant="ghost" onClick={() => setTolerantieDialoog(null)} disabled={dialoogBezig}>
                  Annuleren
                </Button>
                <Button type="submit" disabled={dialoogBezig}>
                  {dialoogBezig ? 'Bezig…' : 'Opslaan'}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
