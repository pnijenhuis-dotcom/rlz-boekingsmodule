import { useNavigate } from 'react-router-dom'
import { Avatar } from '../ui/Avatar'
import { SkeletonRijen } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { heeftOpenstaandWerk, type KlantRij } from './useWerkvoorraadData'

/** Werkvoorraad-ingang (mockup #werkvoorraad "Overzicht per klant"): alleen klanten mét
 * openstaand werk, elke teller klikbaar. De data komt sinds de IA-verbouwing (fase 2) uit de
 * gedeelde hook useWerkvoorraadData — de KPI-rij erboven telt op dezelfde rijen. */

function Teller({ waarde, chipKlasse, label }: { waarde: number; chipKlasse: string; label?: string }) {
  if (waarde === 0) return <>—</>
  return (
    <span className={`chip ${chipKlasse}`}>
      {waarde}
      {label ? ` ${label}` : ''}
    </span>
  )
}

export function Klantenlijst({
  klanten,
  fout,
  onHerlaad,
  totaalAdministraties,
}: {
  klanten: KlantRij[] | null
  fout: string | null
  onHerlaad: () => void
  totaalAdministraties: number
}) {
  const navigate = useNavigate()
  const zichtbaar = (klanten ?? []).filter(heeftOpenstaandWerk)
  const verborgen = (klanten?.length ?? 0) - zichtbaar.length
  // Kolom alleen bij data (Kempen-doorbelasting is voor één administratie relevant — de rest
  // van het kantoor moet geen lege kolom zien).
  const toonSpiegel = (klanten ?? []).some((k) => (k.spiegel_taken ?? 0) > 0)
  // Zelfde toon-regel voor de urenmatch-afwijkingen (factuurmatch fase 2 — alleen relevant
  // voor administraties mét de uren-&-meerwerkmodule, initieel Universal).
  const toonMatch = (klanten ?? []).some((k) => (k.match_afwijkingen ?? 0) > 0)
  // Duplicaatsignaal (besluit 25-08, deel 2 punt 6): zelfde toon-regel — kolom alleen zodra er
  // ergens een gecachet "mogelijk duplicaat in RLZ" staat.
  const toonDuplicaat = (klanten ?? []).some((k) => (k.duplicaat_signalen ?? 0) > 0)

  return (
    <div className="panel">
      <h2>Overzicht per klant</h2>
      {fout && <FoutMelding melding="De klantenlijst kon niet geladen worden." detail={fout} onOpnieuw={onHerlaad} />}
      {!fout && (
        // .tabel-scroll (responsive-fix 2026-08-15): de tellerkolommen + nowrap-chips maken de
        // tabel op smalle vensters breder dan het paneel — dan scrolt de tabel intern i.p.v.
        // door de paneelrand te klippen. sticky-koppen (kliktest 2026-08-21): koppen blijven
        // in beeld bij een lange klantenlijst.
        <div className="tabel-scroll sticky-koppen">
          <table>
            <tbody>
              <tr>
                <th>Administratie</th>
                <th>Te controleren</th>
                <th>Klaar om te boeken</th>
                <th>Vragen</th>
                <th>Afgewezen</th>
                <th>Bij klant (goedkeuring)</th>
                <th>Bank</th>
                {toonSpiegel && <th>Spiegel-taken</th>}
                {toonMatch && <th>Urenmatch</th>}
                {toonDuplicaat && <th>Duplicaten</th>}
              </tr>
              {klanten === null && <SkeletonRijen kolommen={7} rijen={4} />}
              {zichtbaar.map((k) => (
                <tr
                  key={k.administratie_id}
                  className="clickable"
                  onClick={() => navigate(`/?administratie=${k.administratie_id}`)}
                >
                  <td>
                    <div className="naam-met-avatar">
                      <Avatar id={k.administratie_id} naam={k.naam} />
                      <div>
                        <b>{k.naam}</b>{' '}
                        {k.iban_wachtend > 0 && (
                          <span className="chip blokkerend">
                            {k.iban_wachtend} IBAN-{k.iban_wachtend === 1 ? 'accordering' : 'accorderingen'}
                          </span>
                        )}
                      </div>
                    </div>
                  </td>
                  <td>
                    <Teller waarde={k.te_controleren} chipKlasse="ai" />
                  </td>
                  <td>
                    <Teller waarde={k.klaar_om_te_boeken} chipKlasse="klaar" />
                  </td>
                  <td
                    onClick={(e) => {
                      if (k.vragen === 0) return
                      e.stopPropagation()
                      navigate(`/?administratie=${k.administratie_id}&sectie=vragen`)
                    }}
                  >
                    <Teller waarde={k.vragen} chipKlasse="vraag" />
                  </td>
                  <td>
                    <Teller waarde={k.afgewezen} chipKlasse="vraag" />
                  </td>
                  <td>
                    <Teller waarde={k.bij_klant} chipKlasse="geheugen" />
                  </td>
                  <td
                    onClick={(e) => {
                      if (!k.bank_open) return
                      e.stopPropagation()
                      navigate(`/bank/${k.administratie_id}`)
                    }}
                  >
                    {k.bank_open === null ? '—' : <Teller waarde={k.bank_open} chipKlasse="ai" />}
                  </td>
                  {toonSpiegel && (
                    <td title="Open spiegel-taken (doorbelasting): bron geboekt, spiegel-inkoopfactuur in de doel-administratie nog niet">
                      {k.spiegel_taken === null ? '—' : <Teller waarde={k.spiegel_taken} chipKlasse="vraag" />}
                    </td>
                  )}
                  {toonMatch && (
                    <td title="Veldwerker-facturen waarvan de urenmatch afwijkt van de goedgekeurde weekstaten">
                      <Teller waarde={k.match_afwijkingen ?? 0} chipKlasse="vraag" />
                    </td>
                  )}
                  {toonDuplicaat && (
                    <td
                      title="Open documenten waarvan de gecachete RLZ-duplicaatcheck een bestaande factuur met dezelfde crediteur, referentie en bedrag vond"
                      onClick={(e) => {
                        if ((k.duplicaat_signalen ?? 0) === 0) return
                        e.stopPropagation()
                        navigate(`/?administratie=${k.administratie_id}&status=__mogelijk_duplicaat`)
                      }}
                    >
                      <Teller waarde={k.duplicaat_signalen ?? 0} chipKlasse="vraag" />
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {klanten !== null && !fout && zichtbaar.length === 0 && (
        <p className="hint">
          Geen openstaand werk — alle {totaalAdministraties}{' '}
          {totaalAdministraties === 1 ? 'administratie is' : 'administraties zijn'} bij. Nieuwe documenten of
          bankmutaties verschijnen hier vanzelf.
        </p>
      )}
      {klanten !== null && zichtbaar.length > 0 && (
        <p className="hint">
          Alleen klanten mét openstaande zaken staan in deze lijst — is alles geboekt, dan verdwijnt de klant
          automatisch en verschijnt hij weer zodra er iets nieuws binnenkomt. Elke teller is klikbaar.
          {verborgen > 0 && (
            <span style={{ color: 'var(--muted)' }}>
              {' '}
              · {verborgen} {verborgen === 1 ? 'klant' : 'klanten'} zonder openstaande zaken (verborgen)
            </span>
          )}
        </p>
      )}
    </div>
  )
}
