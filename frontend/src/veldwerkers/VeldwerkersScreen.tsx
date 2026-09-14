// Beheer › Veldwerkers — KANTOORBREED (veldwerkers-run 14-09, besluiten Peter 14-09 punt 1+2; UX-norm BESLISSINGEN
// "UX-PATRONEN ALS NORM"): één pagina voor alles wat het kantoor aan een veldwerker beheert — koppelingen
// (detacheerder ↔ ZZP'er, RLZ-crediteur + tarief), bureau-tarieven en het ZZP-dossier. Was tot 14-09 de
// Veldwerkers-tab op Gebruikers & toegang (Beheerder-only); sinds vandaag bereikbaar voor de Beheerder ÓF een
// medewerker met het recht 'veldwerkerbeheer' (backend-poort op GET /uren/beheer/veldgebruikers — de 403 staat hier
// leesbaar). Administratie is een FILTER (doorzoekbare combobox, leeg = alle), nooit een poort; filters reizen mee in
// de URL (?administratie=&filter=dossier_onvolledig&q=) zodat de klantpagina (KlantStanden "ZZP-dossiers — signaal")
// hier kan deeplinken. Eén rij = één veldwerker mét precies één primaire knop ("Dossier" / "ZZP'ers") + ⋯-menu;
// lege stand = actie ("+ Veldwerker uitnodigen"). Accountbeheer (blokkeren, e-mail, herstel-link, archiveren) blijft
// op Gebruikers & toegang › Veldwerkers (Beheerder-only) — daar staat de link hiernaartoe.
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { ActivatiecodeBlok } from '../gebruikers/ActivatiecodeBlok'
import { DossierModal } from '../gebruikers/DossierModal'
import { GebruikerRijMenu, type RijMenuItem } from '../gebruikers/GebruikerRijMenu'
import { activeerLinkUrl, rolLabel } from '../gebruikers/gebruikersApi'
import { UitnodigModal } from '../gebruikers/UitnodigModal'
import { haalVeldgebruikers, type VeldgebruikerDto } from '../meerwerk/meerwerkApi'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { Badge, Button, SkeletonRegels, useToastOptioneel } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { QrLinkDialog } from '../ui/QrLinkDialog'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { dossierStand, isDossierOnvolledig } from './dossierStand'
import {
  BureauTarievenModal,
  CrediteurModal,
  DetacheerderKoppelModal,
  ProjectToegang,
  ZzperBureausModal,
  tariefLabel,
} from './VeldwerkerModals'
import { VeldwerkersTabelKop, veldwerkersTabelStijl } from './VeldwerkersTabelKop'

export const DOSSIER_FILTER = 'dossier_onvolledig'
const DOSSIER_TITEL = 'ZZP-dossier openen (documenten, KvK/btw, herinneringen)'

/** Zoekfilter: naam, e-mail en rol-label (zelfde regel als Gebruikers & toegang). */
export function filterVeldwerkers(
  lijst: VeldgebruikerDto[],
  opties: { administratieId: string; alleenDossierOnvolledig: boolean; zoekterm: string },
): VeldgebruikerDto[] {
  const term = opties.zoekterm.trim().toLowerCase()
  return lijst.filter((v) => {
    if (opties.administratieId && !(v.administratie_ids ?? []).includes(opties.administratieId)) return false
    if (opties.alleenDossierOnvolledig && !isDossierOnvolledig(v)) return false
    if (term && ![v.naam, v.e_mail, rolLabel(v.rol)].join(' ').toLowerCase().includes(term)) return false
    return true
  })
}

/** Urgentie-sortering (KP7 punt 4): onvolledig dossier bovenaan (rood vóór oranje), daarna alfabetisch. */
export function sorteerVeldwerkers(lijst: VeldgebruikerDto[]): VeldgebruikerDto[] {
  const rang = (v: VeldgebruikerDto) => {
    const stand = dossierStand(v)
    if (!stand || !stand.onvolledig) return 2
    return stand.variant === 'danger' ? 0 : 1
  }
  return [...lijst].sort((a, b) => rang(a) - rang(b) || a.naam.localeCompare(b.naam, 'nl'))
}

function StatusChips({ info }: { info: VeldgebruikerDto }) {
  return (
    <div className="chips-regel">
      {info.status === 'actief' && <Badge variant="ok">actief</Badge>}
      {info.status === 'geblokkeerd' && <Badge variant="danger">geblokkeerd</Badge>}
      {info.status === 'gearchiveerd' && <Badge variant="stil">gearchiveerd</Badge>}
      {info.status === 'uitgenodigd' && <Badge variant="stil">uitgenodigd</Badge>}
      {(info.status === 'wacht_op_passkey' || info.status === 'wacht_op_totp') && <Badge variant="warn">activatie onderbroken</Badge>}
    </div>
  )
}

export function VeldwerkersScreen() {
  const { administraties, fout: administratiesFout } = useAdministraties()
  const { meld } = useToastOptioneel()
  const [searchParams, setSearchParams] = useSearchParams()
  const administratieFilter = searchParams.get('administratie') ?? ''
  const dossierFilter = searchParams.get('filter') === DOSSIER_FILTER
  const zoekterm = searchParams.get('q') ?? ''

  const [veld, setVeld] = useState<VeldgebruikerDto[] | null>(null)
  const [fout, setFout] = useState<{ status: number | null; tekst: string } | null>(null)
  const [toonGearchiveerd, setToonGearchiveerd] = useState(false)
  const [projectenUitgeklapt, setProjectenUitgeklapt] = useState<Set<string>>(() => new Set())

  const [zzperBureaus, setZzperBureaus] = useState<VeldgebruikerDto | null>(null)
  const [detacheerderKoppel, setDetacheerderKoppel] = useState<VeldgebruikerDto | null>(null)
  const [crediteurModal, setCrediteurModal] = useState<VeldgebruikerDto | null>(null)
  const [tarievenModal, setTarievenModal] = useState<VeldgebruikerDto | null>(null)
  const [dossierModal, setDossierModal] = useState<VeldgebruikerDto | null>(null)
  const [uitnodigOpen, setUitnodigOpen] = useState(false)
  // Uitnodigingslink als QR + activatiecode (D3 01-09 / app-auth 08-09) — zelfde banner als Gebruikers & toegang.
  const [aanbod, setAanbod] = useState<{ link: string | null; code: string | null } | null>(null)
  const [qrOpen, setQrOpen] = useState(false)
  const [mailFout, setMailFout] = useState<string | null>(null)

  const laad = useCallback(() => {
    setFout(null)
    haalVeldgebruikers()
      .then(setVeld)
      .catch((err: unknown) =>
        setFout(
          err instanceof ApiError
            ? { status: err.status, tekst: err.message }
            : { status: null, tekst: err instanceof Error ? err.message : 'Onbekende fout' },
        ),
      )
  }, [])

  useEffect(() => {
    laad()
  }, [laad])

  /** URL-state (replace: één stap in de historie per pagina, deeplinks blijven deelbaar). */
  function zetParam(naam: string, waarde: string | null) {
    const volgende = new URLSearchParams(searchParams)
    if (waarde === null || waarde === '') volgende.delete(naam)
    else volgende.set(naam, waarde)
    setSearchParams(volgende, { replace: true })
  }

  const alle = veld ?? []
  const gearchiveerdAantal = useMemo(() => alle.filter((v) => v.status === 'gearchiveerd').length, [alle])
  const zichtbaar = useMemo(() => alle.filter((v) => (v.status === 'gearchiveerd') === toonGearchiveerd), [alle, toonGearchiveerd])
  const gefilterd = useMemo(
    () => sorteerVeldwerkers(filterVeldwerkers(zichtbaar, { administratieId: administratieFilter, alleenDossierOnvolledig: dossierFilter, zoekterm })),
    [zichtbaar, administratieFilter, dossierFilter, zoekterm],
  )
  const onvolledigTotaal = useMemo(() => zichtbaar.filter(isDossierOnvolledig).length, [zichtbaar])
  const onvolledigGefilterd = useMemo(() => gefilterd.filter(isDossierOnvolledig).length, [gefilterd])
  const detacheerders = useMemo(() => alle.filter((v) => v.rol === 'detacheerder'), [alle])
  const zzpers = useMemo(() => alle.filter((v) => v.rol === 'zzper'), [alle])
  const bureausVan = (zzperId: string) => detacheerders.filter((d) => d.zzpers.some((z) => z.gebruiker_id === zzperId))
  const filterActief = administratieFilter !== '' || dossierFilter || zoekterm !== ''

  function primaireKnop(info: VeldgebruikerDto): ReactNode {
    if (info.rol === 'detacheerder') {
      return (
        <Button variant="secundair" maat="klein" onClick={() => setDetacheerderKoppel(info)}>
          ZZP'ers
        </Button>
      )
    }
    return (
      <Button variant="secundair" maat="klein" onClick={() => setDossierModal(info)}>
        Dossier
      </Button>
    )
  }

  function menuItems(info: VeldgebruikerDto): RijMenuItem[] {
    const items: RijMenuItem[] = []
    if (info.rol !== 'detacheerder') items.push({ label: 'Dossier openen…', onClick: () => setDossierModal(info) })
    if (info.rol === 'zzper') items.push({ label: 'Detacheerder koppelen…', onClick: () => setZzperBureaus(info) })
    if (info.rol === 'detacheerder') items.push({ label: "ZZP'ers koppelen…", onClick: () => setDetacheerderKoppel(info) })
    if (info.rol !== 'uitvoerder') {
      items.push({ label: info.crediteuren.length === 0 ? 'Crediteur koppelen…' : 'Crediteur/tarief…', onClick: () => setCrediteurModal(info) })
    }
    if (info.rol === 'detacheerder' && info.zzpers.length > 0) {
      items.push({ label: 'Bureau-tarieven…', onClick: () => setTarievenModal(info) })
    }
    return items
  }

  function dossierCel(info: VeldgebruikerDto): ReactNode {
    if (info.rol === 'detacheerder') return <span className="hint" style={{ margin: 0 }}>—</span>
    const stand = dossierStand(info)
    return (
      <button type="button" className="linkbtn" style={{ padding: 0 }} onClick={() => setDossierModal(info)} title={DOSSIER_TITEL}>
        {stand ? <Badge variant={stand.variant}>{stand.label}</Badge> : <Badge variant="stil">📁 dossier</Badge>}
      </button>
    )
  }

  const geenToegang = fout?.status === 403

  return (
    <div>
      <div className="topbar">
        <div>
          <h1>Veldwerkers</h1>
          <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
            ZZP'ers schrijven weekstaten, uitvoerders keuren per week, detacheerders vullen in namens gekoppelde ZZP'ers —
            koppelingen, crediteur + tarieven en het ZZP-dossier voeden de factuurmatch en de WKA-handhaving.
          </div>
        </div>
        {!geenToegang && <Button onClick={() => setUitnodigOpen(true)}>+ Veldwerker uitnodigen</Button>}
      </div>

      {fout && geenToegang && (
        <FoutMelding
          melding="Veldwerkers is alleen toegankelijk voor de Beheerder of een medewerker met het recht 'veldwerkerbeheer' (Gebruikers & toegang › Rechten)."
          detail={fout.tekst}
        />
      )}
      {fout && !geenToegang && <FoutMelding melding="De veldwerkers konden niet geladen worden." detail={fout.tekst} onOpnieuw={laad} />}
      {administratiesFout && <FoutMelding melding="Administraties konden niet geladen worden." detail={administratiesFout} />}
      {mailFout && <FoutMelding melding={mailFout} />}
      {aanbod && (
        <div className="hint" role="status" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }} data-testid="qr-aanbod">
          {aanbod.link && (
            <>
              Uitnodigingslink voor de nieuwe veldwerker — op de bouwplaats scannen?
              <Button variant="secundair" maat="klein" onClick={() => setQrOpen(true)}>
                Toon QR
              </Button>
            </>
          )}
          <ActivatiecodeBlok code={aanbod.code} naam={aanbod.link ? undefined : 'de nieuwe veldwerker'} />
          <button type="button" className="linkbtn" onClick={() => setAanbod(null)}>
            verbergen
          </button>
        </div>
      )}
      <QrLinkDialog link={qrOpen && aanbod?.link ? aanbod.link : null} titel="QR-uitnodiging — nieuwe veldwerker" onSluiten={() => setQrOpen(false)} />

      {!geenToegang && (
        <div className="panel">
          {veld === null && !fout && <SkeletonRegels regels={4} />}
          {veld !== null && alle.length === 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }} data-testid="lege-stand">
              <p className="hint" style={{ margin: 0 }}>
                Nog geen veldwerkers — nodig een ZZP'er, uitvoerder of detacheerder uit.
              </p>
              <Button variant="secundair" maat="klein" onClick={() => setUitnodigOpen(true)}>
                + Veldwerker uitnodigen
              </Button>
            </div>
          )}
          {veld !== null && alle.length > 0 && (
            <>
              {/* Filters = FILTER, nooit poort: administratie (doorzoekbaar), zoekterm, "dossier onvolledig"; alles in de URL. */}
              <div className="lijst-kop" style={{ flexWrap: 'wrap' }}>
                <input
                  type="search"
                  aria-label="Zoek veldwerkers"
                  placeholder="Zoek op naam, e-mail of rol…"
                  value={zoekterm}
                  onChange={(e) => zetParam('q', e.target.value)}
                />
                <div style={{ minWidth: 240 }}>
                  <AdministratieCombobox
                    label="Administratie"
                    toonLabel={false}
                    administraties={administraties ?? []}
                    waarde={administratieFilter}
                    onWijzig={(id) => zetParam('administratie', id)}
                    placeholder="Alle administraties"
                  />
                </div>
                {administratieFilter && (
                  <button type="button" className="linkbtn" onClick={() => zetParam('administratie', null)}>
                    alle administraties
                  </button>
                )}
                <button
                  type="button"
                  className={`chip ${dossierFilter ? 'afwijking' : 'stil'}`}
                  style={{ cursor: 'pointer' }}
                  aria-pressed={dossierFilter}
                  title="Alleen veldwerkers met een ontbrekend, verlopen, binnenkort verlopend of ter-controle-document, of een geblokkeerd dossier"
                  onClick={() => zetParam('filter', dossierFilter ? null : DOSSIER_FILTER)}
                >
                  dossier onvolledig ({onvolledigTotaal})
                </button>
                <span className="hint" style={{ margin: 0 }} data-testid="veldwerkers-teller">
                  {gefilterd.length === zichtbaar.length
                    ? `${zichtbaar.length} ${zichtbaar.length === 1 ? 'veldwerker' : 'veldwerkers'}`
                    : `${gefilterd.length} van ${zichtbaar.length} veldwerkers`}
                  {toonGearchiveerd ? ' (archief)' : ''}
                </span>
                {(gearchiveerdAantal > 0 || toonGearchiveerd) && (
                  <button
                    type="button"
                    className={`chip ${toonGearchiveerd ? 'afwijking' : 'stil'}`}
                    style={{ cursor: 'pointer', marginLeft: 'auto' }}
                    aria-pressed={toonGearchiveerd}
                    onClick={() => setToonGearchiveerd((v) => !v)}
                  >
                    {toonGearchiveerd ? '← actieve veldwerkers' : `gearchiveerd (${gearchiveerdAantal})`}
                  </button>
                )}
              </div>

              {gefilterd.length === 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }} data-testid="lege-filterstand">
                  <p className="hint" style={{ margin: 0 }}>
                    {dossierFilter && !zoekterm ? 'Alle dossiers binnen dit filter zijn compleet.' : 'Geen veldwerkers binnen dit filter.'}
                  </p>
                  {filterActief && (
                    <button type="button" className="linkbtn" onClick={() => setSearchParams({}, { replace: true })}>
                      Filters wissen
                    </button>
                  )}
                </div>
              )}

              {gefilterd.length > 0 && (
                <div className="tabel-scroll sticky-koppen">
                  <table className="gebruikers-tabel" style={veldwerkersTabelStijl()} data-testid="veldwerkers-tabel">
                    <VeldwerkersTabelKop />
                    <tbody>
                      {gefilterd.map((info) => {
                        const bureaus = info.rol === 'zzper' ? bureausVan(info.gebruiker_id) : []
                        return (
                          <tr key={info.gebruiker_id}>
                            <td>
                              <b>{info.naam}</b>
                              <div className="gebruiker-email" title={info.e_mail}>
                                {info.e_mail}
                              </div>
                            </td>
                            <td>
                              <Badge variant="paars">{rolLabel(info.rol)}</Badge>
                            </td>
                            <td>
                              {info.rol !== 'detacheerder' && (
                                <ProjectToegang
                                  info={info}
                                  rol={info.rol}
                                  uitgeklapt={projectenUitgeklapt.has(info.gebruiker_id)}
                                  toggle={() =>
                                    setProjectenUitgeklapt((huidig) => {
                                      const volgende = new Set(huidig)
                                      if (volgende.has(info.gebruiker_id)) volgende.delete(info.gebruiker_id)
                                      else volgende.add(info.gebruiker_id)
                                      return volgende
                                    })
                                  }
                                />
                              )}
                              {bureaus.length > 0 && (
                                <div className="chips-regel" style={{ marginTop: 4 }}>
                                  {bureaus.map((d) => (
                                    <Badge key={d.gebruiker_id} variant="info" title="Detacheerder die weekstaten invult namens deze ZZP'er">
                                      via {d.naam}
                                    </Badge>
                                  ))}
                                </div>
                              )}
                              {info.rol === 'detacheerder' && (
                                <div className="chips-regel">
                                  {info.zzpers.length === 0 && (
                                    <span className="hint" style={{ margin: 0, fontSize: 11 }}>
                                      nog geen ZZP'ers gekoppeld
                                    </span>
                                  )}
                                  {info.zzpers.map((z) => (
                                    <Badge key={z.gebruiker_id} variant="info">
                                      {z.naam}
                                      {z.uurtarief !== null ? ` · ${tariefLabel(z.uurtarief)}` : ' · geen tarief'}
                                    </Badge>
                                  ))}
                                </div>
                              )}
                              {info.rol !== 'uitvoerder' && (
                                <div className="chips-regel" style={{ marginTop: 4 }}>
                                  {info.crediteuren.map((c) => (
                                    <span key={`${c.administratie_id}-${c.vendor_id}`} style={{ display: 'inline-flex', gap: 4 }}>
                                      <Badge variant="stil">
                                        € {c.vendor_naam ?? c.vendor_id}
                                        {c.uurtarief !== null && ` · ${tariefLabel(c.uurtarief)}`}
                                      </Badge>
                                      {c.autoboeken_ingeschakeld && (
                                        <Badge variant="ok" title="Autoboeken bij een groene urenmatch (fase 4) staat aan voor deze koppeling">
                                          ⚡ autoboeken
                                        </Badge>
                                      )}
                                    </span>
                                  ))}
                                  {info.crediteuren.length === 0 && (
                                    <span className="cel-detail" style={{ margin: 0 }}>
                                      zonder crediteur-koppeling geen factuurmatch
                                    </span>
                                  )}
                                </div>
                              )}
                            </td>
                            <td>{dossierCel(info)}</td>
                            <td>
                              <StatusChips info={info} />
                              {info.uren_afwijking_aantal > 0 && (
                                <div
                                  className="cel-detail"
                                  style={{ color: 'var(--warn)' }}
                                  title="Afkeuringen mét correctievoorstel; delta = ingediend − uiteindelijk goedgekeurd. Alleen zichtbaar voor kantoor — de veldwerker ziet dit niet."
                                >
                                  ⚠ {info.uren_afwijking_aantal}× correctie bij keuring ·{' '}
                                  {Number(info.uren_afwijking_som).toLocaleString('nl-NL', { maximumFractionDigits: 2 })} u meer ingediend dan
                                  goedgekeurd
                                </div>
                              )}
                            </td>
                            <td className="acties">
                              <GebruikerRijMenu naam={info.naam} primair={primaireKnop(info)} items={menuItems(info)} />
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="hint" style={{ marginBottom: 0 }} data-testid="veldwerkers-voet">
                {gefilterd.length} {gefilterd.length === 1 ? 'veldwerker' : 'veldwerkers'} · {onvolledigGefilterd} met onvolledig dossier
                {' · '}
                accounts (blokkeren, e-mail, herstel-link, archiveren) beheer je op{' '}
                <Link to="/gebruikers?groep=veldwerkers">Gebruikers &amp; toegang</Link>
              </p>
            </>
          )}
        </div>
      )}

      {uitnodigOpen && (
        <UitnodigModal
          key="veldwerker"
          soort="veldwerker"
          open
          administraties={administraties ?? []}
          onSluiten={() => setUitnodigOpen(false)}
          onUitgenodigd={(resultaat) => {
            const link = resultaat.token ? activeerLinkUrl(resultaat.token) : null
            const code = resultaat.activatiecode ?? null
            if (link || code) setAanbod({ link, code })
            if (resultaat.mail_uitgesteld) {
              meld('Account aangemaakt zonder mail (status uitgenodigd) — nodig later uit via Gebruikers & toegang › "Opnieuw mailen".')
            } else if (resultaat.mail_verzonden) {
              meld('Uitnodiging gemaild — zichtbaar in de lijst tot activatie.')
            } else {
              setMailFout(
                `Uitnodiging aangemaakt, maar het mailen mislukte: ${resultaat.mail_fout ?? 'onbekende mailfout'}. Deel de link of activatiecode handmatig, of gebruik "Opnieuw mailen" op Gebruikers & toegang.`,
              )
            }
            laad()
          }}
        />
      )}
      {zzperBureaus && (
        <ZzperBureausModal
          zzper={zzperBureaus}
          detacheerders={detacheerders}
          onSluiten={() => setZzperBureaus(null)}
          onGewijzigd={() => {
            meld('Detacheerder-koppelingen bijgewerkt — geauditeerd.')
            laad()
          }}
        />
      )}
      {detacheerderKoppel && (
        <DetacheerderKoppelModal
          detacheerder={detacheerderKoppel}
          zzpers={zzpers}
          onSluiten={() => setDetacheerderKoppel(null)}
          onGewijzigd={() => {
            meld("ZZP'er-koppelingen bijgewerkt — geauditeerd.")
            laad()
          }}
        />
      )}
      {crediteurModal && (
        <CrediteurModal
          veldwerker={crediteurModal}
          administraties={administraties ?? []}
          onSluiten={() => setCrediteurModal(null)}
          onGewijzigd={() => {
            meld('Crediteur-koppeling bijgewerkt — geauditeerd.')
            laad()
          }}
        />
      )}
      {dossierModal && (
        <DossierModal veldwerker={dossierModal} administraties={administraties ?? []} onSluiten={() => setDossierModal(null)} onGewijzigd={laad} />
      )}
      {tarievenModal && (
        <BureauTarievenModal
          detacheerder={tarievenModal}
          onSluiten={() => setTarievenModal(null)}
          onGewijzigd={() => {
            meld('Bureau-tarieven bijgewerkt — geauditeerd.')
            laad()
          }}
        />
      )}
    </div>
  )
}
