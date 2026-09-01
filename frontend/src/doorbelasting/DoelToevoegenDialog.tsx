// "+ Doelentiteit toevoegen" (mockup doorbelasting-doel-toevoegen.html = norm, akkoord Peter
// 01-09, casus Mantelzorgwoningen MN): Beheerder-klikwerk naast de seed-CLI. De debiteur in de
// bron-RLZ wordt op naam gezocht; een (bijna-)match wordt GETOOND ter expliciete bevestiging —
// nooit stil gekoppeld (de RLZ-naam kan enkelvoud/meervoud afwijken van de administratienaam);
// geen match = idempotente aanmaak bij opslaan (zorg_voor_debiteur, verkoopmotor-bouwsteen).
// Provisie-GB vooringevuld vanuit de bestaande rijen van dezelfde bron; IC-vlag default aan.
import { useEffect, useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, Switch } from '../ui/basis'
import {
  haalKandidaatDoelenOp,
  maakDoorbelastingMapping,
  zoekDebiteurInBron,
  type DebiteurMatchDto,
  type KandidaatDoelenDto,
} from './doorbelastingApi'
import { useDoelGrootboek } from './useDoelGrootboek'

function kaartTekst(match: DebiteurMatchDto): string {
  const delen = Object.entries(match.kaart).map(([label, waarde]) => `${label}: ${waarde}`)
  return delen.length > 0 ? ` (${delen.join(' · ')})` : ''
}

export function DoelToevoegenDialog({
  administratieId,
  bronNaam,
  onSluiten,
  onToegevoegd,
}: {
  administratieId: string
  bronNaam: string
  onSluiten: () => void
  onToegevoegd: (melding: string) => void
}) {
  const [kandidaten, setKandidaten] = useState<KandidaatDoelenDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [doelId, setDoelId] = useState<string | null>(null)

  // Debiteur-lookup: null = nog niet gezocht (of bezig), lijst = resultaat.
  const [matches, setMatches] = useState<DebiteurMatchDto[] | null>(null)
  const [lookupFout, setLookupFout] = useState<string | null>(null)
  const [gekozenGuid, setGekozenGuid] = useState<string | 'nieuw' | null>(null)
  const [bevestigd, setBevestigd] = useState(false)

  const [provisieLedgerId, setProvisieLedgerId] = useState<string | null>(null)
  const [provisiePrefillGedaan, setProvisiePrefillGedaan] = useState(false)
  const [intercompany, setIntercompany] = useState(true)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const doelNaam = kandidaten?.kandidaten.find((k) => k.id === doelId)?.naam ?? null
  const doelGrootboek = useDoelGrootboek(useMemo(() => [doelId], [doelId]))
  const schema = doelId ? doelGrootboek[doelId] : undefined

  useEffect(() => {
    haalKandidaatDoelenOp(administratieId)
      .then(setKandidaten)
      .catch((err: unknown) => setLaadFout(err instanceof Error ? err.message : 'Laden mislukt'))
  }, [administratieId])

  // Lookup zodra een doel gekozen is — zoeknaam = de administratienaam; de server zoekt exact
  // én met de deterministische bijna-match (enkelvoud/meervoud, rechtsvorm-tolerant).
  useEffect(() => {
    setMatches(null)
    setLookupFout(null)
    setGekozenGuid(null)
    setBevestigd(false)
    if (!doelId || !doelNaam) return
    let actief = true
    zoekDebiteurInBron(administratieId, doelNaam)
      .then((r) => {
        if (!actief) return
        setMatches(r.matches)
        setGekozenGuid(r.matches.length === 0 ? 'nieuw' : r.matches.length === 1 ? r.matches[0].customer_guid : null)
      })
      .catch((err: unknown) => {
        if (actief) setLookupFout(err instanceof ApiError ? err.message : 'Debiteur-lookup mislukt')
      })
    return () => {
      actief = false
    }
  }, [administratieId, doelId, doelNaam])

  // Provisie-GB vooringevuld (mockup ③): de voorgestelde rekeningCODE opzoeken in het schema
  // van het gekozen doel — aanpasbaar, en alleen één keer per gekozen doel prefiller.
  useEffect(() => {
    setProvisieLedgerId(null)
    setProvisiePrefillGedaan(false)
  }, [doelId])
  useEffect(() => {
    if (provisiePrefillGedaan || !schema || schema.laden || !kandidaten?.provisie_voorstel) return
    const voorstel = kandidaten.provisie_voorstel
    const treffer = schema.opties.find((o) => o.code === voorstel.code)
    if (treffer) setProvisieLedgerId(treffer.id)
    setProvisiePrefillGedaan(true)
  }, [schema, kandidaten, provisiePrefillGedaan])

  const gekozenMatch = matches?.find((m) => m.customer_guid === gekozenGuid) ?? null
  const debiteurKlaar =
    matches !== null && (gekozenGuid === 'nieuw' || (gekozenMatch !== null && bevestigd))

  const opslaan = async () => {
    if (!doelId || !doelNaam || !debiteurKlaar) return
    setBezig(true)
    setFout(null)
    try {
      await maakDoorbelastingMapping(administratieId, {
        doel_administratie_id: doelId,
        // Bij een bevestigde match is de RLZ-naam leidend (Mantelzorg-les: enkelvoud in RLZ).
        doelentiteit_naam: gekozenMatch ? gekozenMatch.naam : doelNaam,
        doel_customer_guid: gekozenMatch ? gekozenMatch.customer_guid : null,
        provisie_kosten_ledger_id: provisieLedgerId,
        intercompany,
      })
      onToegevoegd(
        gekozenMatch
          ? `"${gekozenMatch.naam}" toegevoegd aan de whitelist (bestaande RLZ-debiteur gekoppeld) — direct bruikbaar in "Doorbelasten na boeken".`
          : `"${doelNaam}" toegevoegd aan de whitelist (debiteur idempotent aangemaakt in RLZ) — direct bruikbaar in "Doorbelasten na boeken".`,
      )
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Toevoegen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent aria-describedby={undefined} data-testid="doel-toevoegen-dialoog" style={{ maxWidth: 560 }}>
        <DialogTitle>Doelentiteit toevoegen</DialogTitle>
        <DialogDescription>
          Bron: {bronNaam} — de nieuwe rij is direct bruikbaar in &ldquo;Doorbelasten na boeken&rdquo;.
        </DialogDescription>

        {laadFout && <div className="fout">{laadFout}</div>}
        {kandidaten && kandidaten.kandidaten.length === 0 && (
          <p className="hint" style={{ margin: 0 }}>
            Alle onboarded administraties staan al in de whitelist van deze bron.
          </p>
        )}

        {kandidaten && kandidaten.kandidaten.length > 0 && (
          <>
            <div>
              <AdministratieCombobox
                label="Doel-administratie"
                administraties={kandidaten.kandidaten}
                waarde={doelId}
                onWijzig={setDoelId}
                placeholder="— kies doel-administratie —"
                vereist
              />
              <div className="hint" style={{ margin: '4px 0 0' }}>
                Doorzoekbare lijst van onboarded administraties die nog niet in de whitelist staan.
              </div>
            </div>

            {doelId && (
              <div>
                <span className="hint" style={{ margin: '0 0 5px', display: 'block', textTransform: 'uppercase', fontSize: 11, letterSpacing: '.05em', fontWeight: 700 }}>
                  Debiteur in {bronNaam} (RLZ)
                </span>
                {lookupFout && <div className="fout">{lookupFout}</div>}
                {!lookupFout && matches === null && <p className="hint" style={{ margin: 0 }}>Zoeken in Reeleezee…</p>}
                {matches !== null && matches.length === 0 && (
                  <div
                    style={{ background: 'var(--ok-bg, #e4f4ec)', border: '1px solid var(--ok, #1c7a54)', borderRadius: 10, padding: '10px 13px', fontSize: 12.5, color: 'var(--ok, #1c7a54)' }}
                  >
                    Geen bestaande debiteur &ldquo;{doelNaam}&rdquo; gevonden — wordt bij opslaan idempotent
                    aangemaakt in RLZ (zelfde werkwijze als de verkoopboekingen).
                  </div>
                )}
                {matches !== null && matches.length > 0 && (
                  <div style={{ display: 'grid', gap: 6 }}>
                    {matches.map((m) => (
                      <label key={m.customer_guid} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', margin: 0, fontSize: 12.5 }}>
                        <input
                          type="radio"
                          name="debiteur-match"
                          checked={gekozenGuid === m.customer_guid}
                          onChange={() => {
                            setGekozenGuid(m.customer_guid)
                            setBevestigd(false)
                          }}
                        />
                        <span>
                          <b>{m.naam}</b>
                          {kaartTekst(m)}{' '}
                          <span className="hint" style={{ margin: 0 }}>
                            {m.exact ? 'exacte naam-match' : 'bijna-match — controleer of dit dezelfde entiteit is'}
                          </span>
                        </span>
                      </label>
                    ))}
                    <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', margin: 0, fontSize: 12.5 }}>
                      <input
                        type="radio"
                        name="debiteur-match"
                        checked={gekozenGuid === 'nieuw'}
                        onChange={() => {
                          setGekozenGuid('nieuw')
                          setBevestigd(false)
                        }}
                      />
                      <span>
                        Geen van deze — maak een nieuwe debiteur &ldquo;{doelNaam}&rdquo; aan (idempotent, bij opslaan)
                      </span>
                    </label>
                    {gekozenMatch && (
                      <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', margin: '2px 0 0', fontSize: 12.5 }}>
                        <Checkbox
                          checked={bevestigd}
                          onChange={(e) => setBevestigd(e.target.checked)}
                          aria-label="Bevestig dat dit dezelfde entiteit is"
                        />
                        <span>
                          Ik bevestig dat <b>{gekozenMatch.naam}</b> dezelfde entiteit is als{' '}
                          <b>{doelNaam}</b> — de RLZ-naam blijft leidend op de whitelist-rij.
                        </span>
                      </label>
                    )}
                  </div>
                )}
              </div>
            )}

            {doelId && (
              <div>
                <span className="hint" style={{ margin: '0 0 5px', display: 'block', textTransform: 'uppercase', fontSize: 11, letterSpacing: '.05em', fontWeight: 700 }}>
                  Provisierekening (kosten, doel-kant)
                </span>
                {schema?.fout ? (
                  <span className="hint" style={{ margin: 0, color: 'var(--orange, #b45309)' }}>{schema.fout}</span>
                ) : (
                  <SearchableCombobox
                    label={`Provisie-GB in ${doelNaam ?? 'doel'}`}
                    toonLabel={false}
                    opties={schema?.opties ?? []}
                    waarde={provisieLedgerId}
                    onWijzig={setProvisieLedgerId}
                    placeholder="Kies provisie-rekening…"
                  />
                )}
                <div className="hint" style={{ margin: '4px 0 0' }}>
                  {kandidaten.provisie_voorstel
                    ? `Vooringevuld met ${kandidaten.provisie_voorstel.code} · ${kandidaten.provisie_voorstel.naam} (de rekening van de bestaande rijen); aanpasbaar per rij.`
                    : 'Kiesbaar uit het rekeningschema van het doel; ook later aanpasbaar per rij.'}
                </div>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
              <div>
                <span className="hint" style={{ margin: '0 0 3px', display: 'block', textTransform: 'uppercase', fontSize: 11, letterSpacing: '.05em', fontWeight: 700 }}>
                  Intercompany (rekening-courant met de bron)
                </span>
                <div className="hint" style={{ margin: 0, maxWidth: 380 }}>
                  Aan = open posten van dit doel worden uitgesloten van afletter-voorstellen (IC-poort).
                  Alle huidige doelen behalve Rubicon hebben RC met de bron → default aan; achteraf
                  wijzigbaar in de rij-bewerking.
                </div>
              </div>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, whiteSpace: 'nowrap' }}>
                <Switch aria-label="Intercompany" checked={intercompany} onChange={(e) => setIntercompany(e.target.checked)} />
                {intercompany ? 'aan' : 'uit'}
              </label>
            </div>
          </>
        )}

        {fout && <div className="fout">{fout}</div>}

        <DialogFooter>
          <Button variant="ghost" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button onClick={() => void opslaan()} disabled={bezig || !doelId || !debiteurKlaar}>
            {bezig ? 'Bezig…' : 'Toevoegen aan whitelist'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
