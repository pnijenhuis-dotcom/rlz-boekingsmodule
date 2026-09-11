import { PLATFORM_LABELS } from '../gebruikers/gebruikersApi'
import { useCallback, useEffect, useState } from 'react'
import {
  haalAccorderingInstellingen,
  haalAccorderingKandidaten,
  haalApparaten,
  haalStaandeRegels,
  hefVoorstelUitzonderingOp,
  trekApparaatIn,
  trekStaandeRegelIn,
  zetAccorderingInstellingen,
  zetVoorstelNooit,
  type ApparaatDto,
  type KandidaatDto,
  type StaandeRegelDto,
  type VoorstelUitzonderingDto,
} from '../accordering/accorderingApi'
import { apiJson } from '../api/client'
import type { VendorLijstDto, VendorOptieDto } from '../api/types'
import { Select, Switch, SkeletonRegels } from '../ui/basis'
import { rondesTekst } from '../accordering/rondesTekst'
import { IntercompanyLeveranciers } from './IntercompanyLeveranciers'

interface LaagInvoer {
  accordeurId: string
  drempel: string
}

function formatMoment(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('nl-NL', { dateStyle: 'short', timeStyle: 'short' })
}

/** Gekoppelde toestellen en apparaten per accordeur + kill-switch (blok 1c/4 accordeur-PWA, besluit 2026-08-11;
 * app-auth zonder passkey 08-09: toestel-rijen uit de app-activatie naast oude passkey-rijen, die grijs "niet meer
 * gebruikt" tonen zodra de CLI ze markeert — nooit verwijderd). Intrekken trekt de koppeling/passkey én alle
 * sessies van dat apparaat per direct in (server-side, geauditeerd). Beheerder-only — het endpoint weigert andere rollen. */
function AccordeurApparaten({ kandidaten }: { kandidaten: KandidaatDto[] }) {
  const [perGebruiker, setPerGebruiker] = useState<Record<string, ApparaatDto[]>>({})
  const [fout, setFout] = useState<string | null>(null)

  const laad = useCallback(() => {
    setFout(null)
    Promise.all(kandidaten.map(async (k) => [k.id, (await haalApparaten(k.id)).apparaten] as const))
      .then((paren) => setPerGebruiker(Object.fromEntries(paren)))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Apparaten laden mislukt'))
  }, [kandidaten])

  useEffect(() => {
    if (kandidaten.length > 0) laad()
  }, [kandidaten, laad])

  const intrekken = async (apparaatId: string) => {
    setFout(null)
    try {
      await trekApparaatIn(apparaatId)
      laad()
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Intrekken mislukt')
    }
  }

  if (kandidaten.length === 0) return null
  const rijen = kandidaten.flatMap((k) => (perGebruiker[k.id] ?? []).map((a) => ({ kandidaat: k, apparaat: a })))

  return (
    <>
      <h3 style={{ margin: '6px 0 0' }}>Gekoppelde toestellen en apparaten</h3>
      {fout && <div className="fout">{fout}</div>}
      {rijen.length === 0 ? (
        <p className="hint" style={{ margin: 0 }}>
          Nog geen gekoppelde toestellen — een accordeur koppelt zijn toestel bij de activering in de app (link of
          activatiecode uit de uitnodiging).
        </p>
      ) : (
        <>
          <table>
            <thead>
              <tr>
                <th>Accordeur</th>
                <th>Apparaat</th>
                <th>Soort</th>
                <th>Gekoppeld</th>
                <th>Laatst gebruikt</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rijen.map(({ kandidaat, apparaat }) => (
                <tr key={apparaat.id}>
                  <td>{kandidaat.naam}</td>
                  <td style={apparaat.niet_meer_gebruikt_op ? { color: 'var(--muted)' } : undefined}>
                    {apparaat.apparaat_naam ?? 'Onbekend apparaat'}
                    {apparaat.is_dev_stub && <span className="chip"> dev-stub</span>}
                  </td>
                  <td style={apparaat.niet_meer_gebruikt_op ? { color: 'var(--muted)' } : undefined}>
                    {apparaat.soort === 'toestel'
                      ? `Toestel${apparaat.platform ? ` (${PLATFORM_LABELS[apparaat.platform] ?? apparaat.platform})` : ''}`
                      : apparaat.niet_meer_gebruikt_op
                        ? 'passkey — niet meer gebruikt'
                        : 'passkey'}
                  </td>
                  <td>{formatMoment(apparaat.aangemaakt_op)}</td>
                  <td>{formatMoment(apparaat.laatst_gebruikt_op)}</td>
                  <td>
                    {apparaat.ingetrokken_op ? (
                      <span className="chip">ingetrokken</span>
                    ) : apparaat.niet_meer_gebruikt_op ? (
                      <span className="chip" title="Passkey van een app-gebruiker, niet meer in gebruik — nooit verwijderd; intrekken kan nog">
                        niet meer gebruikt
                      </span>
                    ) : (
                      <span className="chip geheugen">actief</span>
                    )}
                  </td>
                  <td>
                    {!apparaat.ingetrokken_op && (
                      <button
                        type="button"
                        className="btn secondary"
                        onClick={() => void intrekken(apparaat.id)}
                      >
                        Toegang intrekken
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="hint" style={{ margin: 0 }}>
            Intrekken (kill-switch) blokkeert dit apparaat per direct: de toestelkoppeling of passkey én alle lopende
            sessies vervallen — de accordeur kan alleen opnieuw beginnen met een nieuwe uitnodiging of herstel-link
            (link of activatiecode) op een toestel.
          </div>
        </>
      )}
    </>
  )
}

/** Accordering-beheer voor één administratie (mockup #autorisatie, Beheerder-only): toggle,
 * sequentiële lagen met bedragdrempels, en de staande goedkeuringen (zichtbaar + intrekbaar —
 * besluit 2026-08-08). Sequentieel: laag 1 eerst, laag 2 alleen als de drempelvoorwaarde
 * geldt. */
function AdministratieAccordering({ administratieId, naam }: { administratieId: string; naam: string }) {
  const [geladen, setGeladen] = useState(false)
  const [ingeschakeld, setIngeschakeld] = useState(false)
  const [lagen, setLagen] = useState<LaagInvoer[]>([])
  const [kandidaten, setKandidaten] = useState<KandidaatDto[]>([])
  const [staandeRegels, setStaandeRegels] = useState<StaandeRegelDto[]>([])
  const [uitzonderingen, setUitzonderingen] = useState<VoorstelUitzonderingDto[]>([])
  const [crediteuren, setCrediteuren] = useState<VendorOptieDto[]>([])
  const [nooitVendor, setNooitVendor] = useState('')
  const [nooitReden, setNooitReden] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [melding, setMelding] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)

  const laad = useCallback(() => {
    setFout(null)
    Promise.all([
      haalAccorderingInstellingen(administratieId),
      haalAccorderingKandidaten(administratieId),
      haalStaandeRegels(administratieId),
    ])
      .then(([instellingen, kandidatenDto, regelsDto]) => {
        setIngeschakeld(instellingen.ingeschakeld)
        setLagen(
          instellingen.lagen.map((laag) => ({
            accordeurId: laag.accordeur_gebruiker_id,
            drempel: laag.bedrag_drempel ?? '',
          })),
        )
        setKandidaten(kandidatenDto.kandidaten)
        setStaandeRegels(regelsDto.regels)
        setUitzonderingen(regelsDto.uitzonderingen ?? [])
        setGeladen(true)
      })
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
    // Crediteurenlijst voor "Nooit voorstellen…" (blok 7 11-09) — verrijking, nooit blokkerend voor het scherm.
    apiJson<VendorLijstDto>(`/administraties/${administratieId}/crediteuren`)
      .then((lijst) => setCrediteuren(lijst.crediteuren))
      .catch(() => setCrediteuren([]))
  }, [administratieId])

  const opslaan = async () => {
    setBezig(true)
    setFout(null)
    setMelding(null)
    try {
      const resultaat = await zetAccorderingInstellingen(administratieId, {
        ingeschakeld,
        lagen: lagen
          .filter((laag) => laag.accordeurId)
          .map((laag, index) => ({
            volgnummer: index + 1,
            accordeur_gebruiker_id: laag.accordeurId,
            bedrag_drempel: laag.drempel ? laag.drempel.replace(',', '.') : null,
          })),
      })
      // Bundel 09-09 blok 2 (besluit Peter 08-09): een schemawijziging HERBEREKENT lopende rondes — gegeven
      // akkoorden blijven staan waar ze passen, ontbrekende lagen worden opnieuw aangevraagd. Alleen een ronde
      // waarvan geen enkel akkoord meer past vervalt (dan staat de eenmalige banner op de documentenlijst).
      setMelding(`Opgeslagen.${rondesTekst(resultaat.rondes_herberekend ?? 0, resultaat.rondes_vervallen ?? 0)}`)
      laad()
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Opslaan mislukt')
    } finally {
      setBezig(false)
    }
  }

  const nooitVoorstellen = async (vendorId: string, reden: string | null) => {
    setFout(null)
    try {
      await zetVoorstelNooit(administratieId, { vendor_id: vendorId, reden, accordeur_gebruiker_id: null })
      setNooitVendor('')
      setNooitReden('')
      laad()
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Instellen mislukt')
    }
  }

  const uitzonderingOpheffen = async (rijId: string) => {
    setFout(null)
    try {
      await hefVoorstelUitzonderingOp(administratieId, rijId)
      laad()
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Opheffen mislukt')
    }
  }

  const regelIntrekken = async (regelId: string) => {
    setFout(null)
    try {
      await trekStaandeRegelIn(administratieId, regelId)
      laad()
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Intrekken mislukt')
    }
  }

  return (
    <details onToggle={(e) => (e.target as HTMLDetailsElement).open && !geladen && laad()}>
      <summary style={{ cursor: 'pointer', padding: '6px 0' }}>
        <b>{naam}</b>
      </summary>
      {fout && <div className="fout">{fout}</div>}
      {!geladen && !fout ? (
        <SkeletonRegels />
      ) : geladen ? (
        <div style={{ display: 'grid', gap: 10, padding: '6px 0 12px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
            <Switch checked={ingeschakeld} onChange={(e) => setIngeschakeld(e.target.checked)} />
            Goedkeuring door klant vereist (boekknop wordt &ldquo;Ter accordering&rdquo;)
          </label>
          {kandidaten.length === 0 && (
            <p className="hint" style={{ margin: 0 }}>
              Geen klant-accordeurs met toegang tot deze administratie — nodig eerst een gebruiker uit met de rol
              Klant-accordeur en koppel die aan deze administratie.
            </p>
          )}
          {lagen.map((laag, index) => (
            <div key={index} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ minWidth: 52 }}>Laag {index + 1}</span>
              <Select
                aria-label={`Accordeur laag ${index + 1}`}
                value={laag.accordeurId}
                onChange={(e) =>
                  setLagen((huidig) =>
                    huidig.map((l, i) => (i === index ? { ...l, accordeurId: e.target.value } : l)),
                  )
                }
              >
                <option value="">— kies accordeur —</option>
                {kandidaten.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.naam}
                  </option>
                ))}
              </Select>
              <input
                aria-label={`Bedragdrempel laag ${index + 1}`}
                placeholder="drempel (leeg = alle facturen)"
                style={{ width: 220 }}
                value={laag.drempel}
                onChange={(e) =>
                  setLagen((huidig) => huidig.map((l, i) => (i === index ? { ...l, drempel: e.target.value } : l)))
                }
              />
              <button
                type="button"
                className="btn secondary"
                onClick={() => setLagen((huidig) => huidig.filter((_, i) => i !== index))}
              >
                Verwijderen
              </button>
            </div>
          ))}
          <div className="actions" style={{ margin: 0 }}>
            <button
              type="button"
              className="btn secondary"
              onClick={() => setLagen((huidig) => [...huidig, { accordeurId: '', drempel: '' }])}
            >
              + Laag toevoegen
            </button>
            <button type="button" className="btn" disabled={bezig} onClick={() => void opslaan()}>
              {bezig ? 'Opslaan…' : 'Opslaan'}
            </button>
            {melding && <span className="hint">{melding}</span>}
          </div>
          <div className="hint" style={{ margin: 0 }}>
            Sequentieel: eerst laag 1 akkoord, dan pas laag 2 (indien de drempelvoorwaarde geldt). Na het laatste
            akkoord boekt de motor automatisch — de harde checks draaien dan onverkort opnieuw.
          </div>
          {staandeRegels.length > 0 && (
            <>
              <h3 style={{ margin: '6px 0 0' }}>Staande goedkeuringen</h3>
              <table>
                <thead>
                  <tr>
                    <th>Accordeur</th>
                    <th>Leverancier</th>
                    <th className="amount">Bedrag (exact)</th>
                    <th>Status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {staandeRegels.map((regel) => (
                    <tr key={regel.id}>
                      <td>{regel.accordeur_naam ?? regel.accordeur_gebruiker_id}</td>
                      <td>{regel.leverancier_naam ?? regel.vendor_id}</td>
                      <td className="amount">€ {regel.bedrag}</td>
                      <td>
                        {regel.actief ? (
                          <span className="chip geheugen">actief</span>
                        ) : (
                          <span className="chip">ingetrokken</span>
                        )}
                      </td>
                      <td>
                        {regel.actief && (
                          <button
                            type="button"
                            className="btn secondary"
                            onClick={() => void regelIntrekken(regel.id)}
                          >
                            Intrekken
                          </button>
                        )}
                        {!uitzonderingen.some((u) => u.vendor_id === regel.vendor_id && u.soort === 'nooit') && (
                          <button
                            type="button"
                            className="linkbtn"
                            style={{ marginLeft: 8 }}
                            onClick={() => void nooitVoorstellen(regel.vendor_id, null)}
                          >
                            Nooit voorstellen
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="hint" style={{ margin: 0 }}>
                Een staande goedkeuring vervangt alleen de akkoord-klik van die accordeur bij exact hetzelfde
                bedrag van dezelfde leverancier — de harde checks (duplicaat, IBAN-wissel, regels) blijven
                onverkort blokkerend. Afwijkend bedrag = gewoon ter accordering.
              </div>
            </>
          )}
          <VoorstelUitzonderingen
            uitzonderingen={uitzonderingen}
            crediteuren={crediteuren}
            nooitVendor={nooitVendor}
            nooitReden={nooitReden}
            onVendor={setNooitVendor}
            onReden={setNooitReden}
            onZet={() => nooitVendor && void nooitVoorstellen(nooitVendor, nooitReden || null)}
            onOpheffen={(id) => void uitzonderingOpheffen(id)}
          />
          <AccordeurApparaten kandidaten={kandidaten} />
        </div>
      ) : null}
    </details>
  )
}

export function AccorderingInstellingen({
  administraties,
}: {
  administraties: { id: string; naam: string }[]
}) {
  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h2>Klant-accordering (goedkeuring door klanten)</h2>
      <p className="hint" style={{ marginTop: 4 }}>
        Optioneel per administratie (mockup Autorisatie): accordeurs in sequentiële lagen, met optionele
        bedragdrempel per laag. De accordeur werkt straks in de mobiele goedkeur-app; dit is het kantoorbeheer.
      </p>
      {administraties.map((a) => (
        <AdministratieAccordering key={a.id} administratieId={a.id} naam={a.naam} />
      ))}
      {/* Nachtrun 08/09-09 blok 1: intercompany-leveranciers per administratie — alleen op de detailpagina (één
          administratie); de kantoorbrede sectie toont het niet (daar zou het N blokken worden). */}
      {administraties.length === 1 && (
        <IntercompanyLeveranciers administratieId={administraties[0].id} naam={administraties[0].naam} />
      )}
    </div>
  )
}


/** "Nooit voorstellen" per leverancier (blok 7 run 11-09 middag, casus Lusso): het staande-goedkeuring-voorstel in de
 * accordeur-app zwijgt voor deze leverancier — administratiebreed (Beheerder) of door de accordeur zelf. Raakt de
 * staande goedkeuringen niet. Lopende "niet nu"-stiltes (90 dagen) staan er ter informatie bij. */
function VoorstelUitzonderingen({
  uitzonderingen,
  crediteuren,
  nooitVendor,
  nooitReden,
  onVendor,
  onReden,
  onZet,
  onOpheffen,
}: {
  uitzonderingen: VoorstelUitzonderingDto[]
  crediteuren: VendorOptieDto[]
  nooitVendor: string
  nooitReden: string
  onVendor: (v: string) => void
  onReden: (v: string) => void
  onZet: () => void
  onOpheffen: (id: string) => void
}) {
  const alGezet = new Set(uitzonderingen.filter((u) => u.soort === 'nooit').map((u) => u.vendor_id))
  return (
    <div data-testid="voorstel-uitzonderingen" style={{ display: 'grid', gap: 8 }}>
      <h3 style={{ margin: '6px 0 0' }}>Voorstel "voortaan automatisch akkoord?" in de app</h3>
      <div className="hint" style={{ margin: 0 }}>
        De app stelt een staande goedkeuring alleen voor bij een terugkerend patroon (elke maand of elk kwartaal
        hetzelfde bedrag) — nooit bij een reeks gelijke facturen binnen een paar weken, zoals twaalf chalets in één
        week. Hier zet u een leverancier op "nooit voorstellen" voor alle accordeurs van deze administratie.
      </div>
      {uitzonderingen.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Leverancier</th>
              <th>Geldt voor</th>
              <th>Status</th>
              <th>Reden</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {uitzonderingen.map((u) => (
              <tr key={u.id} data-uitzondering={u.soort}>
                <td>{u.leverancier_naam ?? u.vendor_id}</td>
                <td>{u.accordeur_gebruiker_id ? (u.accordeur_naam ?? u.accordeur_gebruiker_id) : 'alle accordeurs'}</td>
                <td>
                  {u.soort === 'nooit' ? (
                    <span className="chip">nooit voorstellen</span>
                  ) : (
                    <span className="chip">stil tot {u.stil_tot ?? '—'}</span>
                  )}
                </td>
                <td>{u.reden ?? ''}</td>
                <td>
                  <button type="button" className="btn secondary" onClick={() => onOpheffen(u.id)}>
                    Opheffen
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <Select
          aria-label="Leverancier voor nooit voorstellen"
          value={nooitVendor}
          onChange={(e) => onVendor(e.target.value)}
        >
          <option value="">Leverancier kiezen…</option>
          {crediteuren
            .filter((c) => !alGezet.has(c.id))
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.naam ?? c.id}
              </option>
            ))}
        </Select>
        <input
          aria-label="Reden nooit voorstellen"
          placeholder="Reden (optioneel)"
          value={nooitReden}
          onChange={(e) => onReden(e.target.value)}
          style={{ minWidth: 220 }}
        />
        <button type="button" className="btn secondary" disabled={!nooitVendor} onClick={onZet}>
          Nooit voorstellen
        </button>
      </div>
    </div>
  )
}
