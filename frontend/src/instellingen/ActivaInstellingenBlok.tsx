import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import {
  haalActivaInstelling,
  methodeNaamVoorMaanden,
  TERMIJN_OPTIES_MAANDEN,
  zetActivaInstelling,
  type ActivaInstellingBody,
  type ActivaInstellingDto,
} from '../activa/activaApi'
import { useAuthOptioneel } from '../auth/AuthContext'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { Badge, Select, Switch } from '../ui/basis'
import { formatBedrag, formatDatumKort } from '../werkvoorraad/format'

/** Activa / MVA per administratie (fase 1, ontwerp docs/ONTWERP_ACTIVA_MVA.md, akkoord Peter 21-09; migratie 0168): blok op
 * de tab "Boeken & AI" ná "Btw niet aftrekbaar" (anker `activa`, registry-entry). Autoboek-patroon: de schakelaar "Activum
 * automatisch aanmaken ná boeken" staat default UIT — aan = élke kandidaat (regel op een activarekening ≥ grens) wordt ná
 * de boeking zonder mens een activum in Reeleezee (herkomst `automatisch`, audit, mislukt = zichtbaar, nooit stil). De
 * activeringsgrens komt uit Reeleezee (`FixedAssetAlertAmount`) als die gevuld is — bron wint, de eigen waarde is de
 * terugval. Per categorie (rekeningnaam → categorie, pure code) de termijn (lineair, 1–50 jaar) en de afschrijvingsrekening
 * die de motor gebruikt als de kaart niets anders zegt. Registerstand = de laatste probe op `FixedAssets` (403 = recht
 * "Vaste activa" ontbreekt op de webservice-login). Beheerder muteert (server-side poort); andere rollen lezen. */

function grensNaarServer(invoer: string): string | null {
  const schoon = invoer.trim().replace(/\s|€/g, '').replace(',', '.')
  if (schoon === '') return null
  const n = Number(schoon)
  if (!Number.isFinite(n) || n < 0) return null
  return n.toFixed(2)
}

function grensNaarInvoer(server: string): string {
  const n = Number(server)
  return Number.isFinite(n) ? n.toFixed(2).replace('.', ',') : server
}

export function ActivaInstellingenBlok({ administratieId, naam, uitgeschakeld = false }: { administratieId: string; naam: string; uitgeschakeld?: boolean }) {
  const auth = useAuthOptioneel()
  // Beheerder muteert; andere kantoorrollen lezen (server-side poort op de PUT). Zonder auth-context (harnas/tests) = muteerbaar.
  const magMuteren = auth === null || auth.rol === 'beheerder'
  const [stand, setStand] = useState<ActivaInstellingDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [aan, setAan] = useState(false)
  const [grens, setGrens] = useState('')
  const [termijnen, setTermijnen] = useState<Record<string, number>>({})
  const [ledgers, setLedgers] = useState<Record<string, string>>({})
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [opgeslagen, setOpgeslagen] = useState(false)

  const neemOver = useCallback((data: ActivaInstellingDto) => {
    setStand(data)
    setAan(data.automatisch_aanmaken_ingeschakeld)
    setGrens(grensNaarInvoer(data.activeringsgrens))
    const t: Record<string, number> = {}
    for (const c of data.categorieen) t[c.code] = data.termijnen[c.code] ?? c.default_maanden
    setTermijnen(t)
    setLedgers({ ...data.afschrijving_ledgers })
  }, [])

  const laad = useCallback(async () => {
    setLaadFout(null)
    try {
      neemOver(await haalActivaInstelling(administratieId))
    } catch (err) {
      setStand(null)
      setLaadFout(err instanceof ApiError ? err.message : 'Instelling niet beschikbaar.')
    }
  }, [administratieId, neemOver])

  useEffect(() => {
    void laad()
  }, [laad])

  const grensServer = grensNaarServer(grens)
  const grensOngeldig = grensServer === null

  const gewijzigd = useMemo(() => {
    if (!stand) return false
    if (aan !== stand.automatisch_aanmaken_ingeschakeld) return true
    if (grensServer !== null && grensServer !== Number(stand.activeringsgrens).toFixed(2)) return true
    for (const c of stand.categorieen) {
      if ((termijnen[c.code] ?? c.default_maanden) !== (stand.termijnen[c.code] ?? c.default_maanden)) return true
      if ((ledgers[c.code] ?? null) !== (stand.afschrijving_ledgers[c.code] ?? null)) return true
    }
    return false
  }, [stand, aan, grensServer, termijnen, ledgers])

  const ledgerOpties = useMemo(
    () => stand?.afschrijving_ledger_opties.map((o) => ({ id: o.ledger_id, code: o.code, label: o.naam })) ?? [],
    [stand],
  )

  const opslaan = async () => {
    if (!stand || grensServer === null) return
    setBezig(true)
    setFout(null)
    setOpgeslagen(false)
    const body: ActivaInstellingBody = {
      automatisch_aanmaken_ingeschakeld: aan,
      activeringsgrens: grensServer,
      termijnen: Object.fromEntries(stand.categorieen.map((c) => [c.code, termijnen[c.code] ?? c.default_maanden])),
      afschrijving_ledgers: Object.fromEntries(Object.entries(ledgers).filter(([, id]) => Boolean(id))),
    }
    try {
      neemOver(await zetActivaInstelling(administratieId, body))
      setOpgeslagen(true)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  const dicht = uitgeschakeld || bezig || !magMuteren
  const tellers = stand?.koppelingen_tellers
  const registerTekst = (() => {
    if (!stand) return null
    const gemeten = stand.register_geprobeerd_op ? ` — gemeten ${formatDatumKort(stand.register_geprobeerd_op)}` : ''
    if (stand.register_leesbaar === true) return { variant: 'ok' as const, tekst: `activaregister leesbaar${gemeten}` }
    if (stand.register_leesbaar === false)
      return { variant: 'warn' as const, tekst: `recht ontbreekt (403) — RLZ-recht "Vaste activa" op de webservice-login zetten${gemeten}` }
    return { variant: 'stil' as const, tekst: 'registerstand nog niet gemeten (volgt bij de eerstvolgende sync)' }
  })()

  return (
    <div className="panel" id="activa" data-testid="activa-instellingen-blok" style={{ padding: 12, marginTop: 12 }}>
      <h2 style={{ marginTop: 0 }}>Activa / MVA — activum aanmaken ná boeken</h2>
      <p className="hint" style={{ marginTop: 0 }}>
        Een inkoopregel op een activarekening van minstens de activeringsgrens krijgt op het controlescherm de kaart "Activum aanmaken?"
        met voorgevulde waarden; ná boeken maakt de module het activum aan in het register van Reeleezee (Reeleezee schrijft af, de
        module rekent niets en verwijdert nooit). De schakelaar hieronder laat dat zonder mens gebeuren — zoals elk autoboek-pad: default
        uit, harde controles blijven de poort, mislukt is zichtbaar.
      </p>
      {laadFout && (
        <div className="fout" role="alert">
          {laadFout}
        </div>
      )}
      {stand && (
        <>
          {!magMuteren && (
            <p className="hint" data-testid="activa-lezen-hint" style={{ marginTop: 0 }}>
              Alleen een Beheerder wijzigt deze instellingen; u ziet de huidige stand.
            </p>
          )}
          <div className="inst-rij">
            <div className="inst-rij-tekst">
              <div className="inst-rij-titel">Activum automatisch aanmaken ná boeken</div>
              <div className="hint">
                Aan = élke kandidaat wordt ná de boeking automatisch een activum (chip "automatisch", audit); ontbreekt een
                afschrijvingsrekening, dan staat dat als "mislukt" op de kaart en in de dagelijkse controle — nooit stil. Uit = een mens
                kiest per regel op het controlescherm.
              </div>
            </div>
            <label className="inst-switch-label">
              <Switch
                aria-label={`Activum automatisch aanmaken ná boeken voor ${naam}`}
                checked={aan}
                disabled={dicht}
                onChange={(e) => {
                  setOpgeslagen(false)
                  setAan(e.target.checked)
                }}
              />
              {aan ? 'aan' : 'uit'}
            </label>
          </div>

          <div className="inst-rij">
            <div className="inst-rij-tekst">
              <div className="inst-rij-titel">Activeringsgrens (excl. btw)</div>
              <div className="hint">
                Onder deze grens is een aanschaf op een activarekening een kleine aanschaf (oranje signaal, geen activum).
                {stand.grens_rlz !== null ? (
                  <span data-testid="activa-grens-rlz">
                    {' '}
                    Reeleezee: {formatBedrag(stand.grens_rlz)} — bron wint; de eigen waarde geldt alleen als Reeleezee niets zegt.
                  </span>
                ) : (
                  ' Reeleezee heeft geen grens ingesteld — de eigen waarde geldt.'
                )}
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className="hint">€</span>
              <input
                aria-label={`Activeringsgrens voor ${naam}`}
                value={grens}
                disabled={dicht}
                inputMode="decimal"
                style={{ width: 110, textAlign: 'right' }}
                onChange={(e) => {
                  setOpgeslagen(false)
                  setGrens(e.target.value)
                }}
              />
              {grensOngeldig && (
                <span className="text-[12px] text-red" role="alert">
                  bedrag ≥ 0 verwacht
                </span>
              )}
            </div>
          </div>

          <div className="tabel-scroll" style={{ marginTop: 8 }}>
            <table className="lines" data-testid="activa-categorie-tabel" style={{ minWidth: 640 }}>
              <thead>
                <tr>
                  <th>Categorie (uit de rekeningnaam)</th>
                  <th>Termijn (lineair)</th>
                  <th>Afschrijvingsrekening</th>
                </tr>
              </thead>
              <tbody>
                {stand.categorieen.map((c) => (
                  <tr key={c.code}>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <b>{c.label}</b>
                      <div className="hint">default {methodeNaamVoorMaanden(c.default_maanden)}</div>
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <Select
                        aria-label={`Termijn ${c.label}`}
                        value={String(termijnen[c.code] ?? c.default_maanden)}
                        disabled={dicht}
                        onChange={(e) => {
                          setOpgeslagen(false)
                          setTermijnen((t) => ({ ...t, [c.code]: Number(e.target.value) }))
                        }}
                      >
                        {TERMIJN_OPTIES_MAANDEN.map((m) => (
                          <option key={m} value={m}>
                            {m / 12} jaar
                          </option>
                        ))}
                      </Select>
                    </td>
                    <td style={{ minWidth: 260 }}>
                      <SearchableCombobox
                        label={`Afschrijvingsrekening ${c.label}`}
                        toonLabel={false}
                        opties={ledgerOpties}
                        waarde={ledgers[c.code] ?? null}
                        onWijzig={(id) => {
                          setOpgeslagen(false)
                          setLedgers((l) => {
                            const n = { ...l }
                            if (id) n[c.code] = id
                            else delete n[c.code]
                            return n
                          })
                        }}
                        placeholder={ledgerOpties.length === 0 ? 'Geen 0xxx-rekening in de sync' : 'Kies rekening…'}
                        leegTekst="Geen afschrijvingsrekening (0xxx) in deze administratie"
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 10, alignItems: 'flex-start' }}>
            <div style={{ flex: '1 1 260px', minWidth: 0 }}>
              <div className="inst-rij-titel">Activarekeningen ({stand.mva_rekeningen.length})</div>
              {stand.mva_rekeningen.length === 0 ? (
                <div className="hint" data-testid="activa-mva-leeg">
                  Geen activarekening herkend in de grootboek-sync (vlag "vaste activa" + balans + 0xxx) — de kaart verschijnt pas als er een is.
                </div>
              ) : (
                <div className="hint" data-testid="activa-mva-lijst" style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {stand.mva_rekeningen.map((r) => (
                    <span key={r.ledger_id} className="chip geboekt" title={r.naam}>
                      {r.code} {r.naam}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div style={{ flex: '1 1 260px', minWidth: 0 }}>
              <div className="inst-rij-titel">Register in Reeleezee</div>
              {registerTekst && (
                <Badge variant={registerTekst.variant} data-testid="activa-registerstand">
                  {registerTekst.tekst}
                </Badge>
              )}
              {stand.register_fout && stand.register_leesbaar === false && <div className="hint">{stand.register_fout}</div>}
              {tellers && (
                <div className="hint" data-testid="activa-tellers" style={{ marginTop: 6 }}>
                  koppelingen: {tellers.aangemaakt} aangemaakt · {tellers.gepland} gepland · {tellers.overgeslagen} niet geactiveerd ·{' '}
                  {tellers.mislukt} mislukt · {tellers.beoordelen} beoordelen
                </div>
              )}
            </div>
          </div>

          <div className="actions" style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'flex-start' }}>
            <button type="button" className="btn" disabled={!gewijzigd || grensOngeldig || dicht} onClick={() => void opslaan()}>
              Opslaan
            </button>
            {opgeslagen && !fout && <span className="text-[12px] text-ok">opgeslagen</span>}
            {fout && (
              <span className="text-[12px] text-red" role="alert">
                {fout}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  )
}
