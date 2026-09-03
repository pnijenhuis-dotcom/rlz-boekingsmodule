import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import type { AdministratieDto } from '../api/types'
import { useAuthOptioneel } from '../auth/AuthContext'
import { haalDubbelenStandOp } from '../crediteuren/api'
import { haalAiKostenStatusOp, type AiKostenStatusDto } from '../instellingen/instellingenApi'
import { VerzamelbakPaneel } from '../intake/VerzamelbakPaneel'
import { verwerkEml, verwerkLosBestand } from '../intake/intakeApi'
import { FoutMelding } from '../ui/FoutMelding'
import { Lichtbaan } from '../ui/Lichtbaan'
import { VragenScreen } from '../vragen/VragenScreen'
import { DocumentenDeelscherm } from './DocumentenDeelscherm'
import { FilterWeergave, type WerkvoorraadFilter } from './FilterWeergave'
import { Klantenlijst } from './Klantenlijst'
import { KlantStanden } from './KlantStanden'
import { KpiRij } from './KpiRij'
import { UploadZone } from './UploadZone'
import { teVerwerken, useWerkvoorraadData, type KlantRij } from './useWerkvoorraadData'
import { useAdministraties } from './useAdministraties'

/** IA (designronde 15-08, mockup/kantoor-modern.html) — HERZIEN 25-08 (besluit Peter, feedbackronde
 * punt C: "twee kliks is omslachtig"): de klant-klik landt DIRECT op de documentenlijst.
 * `/` = werkvoorraad (KPI's + upload + verzamelbak + klantenlijst);
 * `/?filter=` = kantoorbrede dwarsdoorsnede (klikbare KPI-kaart);
 * `/?administratie=[&soort=][&status=]` = klantlanding: te-verwerken-documenten mét tabs per soort
 *   en een chip-rij met de overige standen (`sectie=documenten` blijft als alias werken);
 * `/?administratie=&sectie=standen` = het standen-overzicht (voorheen de verplichte tussenlaag);
 * `/?administratie=&sectie=vragen[&document=]` = vragen-deelscherm. Oude URL's blijven werken. */
export function WerkvoorraadScreen() {
  const { administraties, fout: administratiesFout } = useAdministraties()
  const [searchParams] = useSearchParams()
  const administratieId = searchParams.get('administratie')
  const sectie = searchParams.get('sectie')
  const filter = searchParams.get('filter')

  if (administratiesFout) {
    return (
      <FoutMelding
        melding="Uw administraties konden niet geladen worden. Controleer de verbinding en probeer het opnieuw."
        detail={administratiesFout}
        onOpnieuw={() => window.location.reload()}
      />
    )
  }
  if (!administraties) {
    return (
      <div className="panel" aria-busy="true">
        <span className="skeleton" style={{ width: '40%', marginBottom: 10 }} />
        <span className="skeleton" style={{ width: '70%' }} />
      </div>
    )
  }
  if (administraties.length === 0) {
    return <p className="hint">Geen administraties gekoppeld aan uw account.</p>
  }

  if (administratieId) {
    const administratie = administraties.find((a) => a.id === administratieId)
    const naam = administratie?.naam ?? 'Onbekende administratie'
    if (sectie === 'vragen') {
      return <VragenScreen />
    }
    if (sectie === 'standen') {
      return <KlantStanden administratieId={administratieId} administratieNaam={naam} />
    }
    // Landing (besluit 25-08) — óók voor de oude `sectie=documenten`-URL's.
    return <DocumentenDeelscherm administratieId={administratieId} administratieNaam={naam} />
  }

  return <WerkvoorraadIngang administraties={administraties} filter={filter} />
}

/** AI-kostenmelding (besluit 2026-08-14): de werkvoorraad blijft het meldingskanaal voor de
 * 80%-/100%-drempels (éénmalig per maand, hard besluit AI-kostengrens) — de kóstenmeter zelf
 * leeft sinds de designronde 15-08 alleen nog op Instellingen (Beheerder). */
function AiKostenBanner() {
  const rol = useAuthOptioneel()?.rol ?? null
  const [status, setStatus] = useState<AiKostenStatusDto | null>(null)
  useEffect(() => {
    if (rol !== 'beheerder') return
    haalAiKostenStatusOp()
      .then(setStatus)
      .catch(() => undefined) // melding is best-effort; de harde poort zit in de backend
  }, [rol])
  if (!status || (!status.waarschuwing_80 && !status.limiet_bereikt)) return null
  if (status.limiet_bereikt) {
    return (
      <div className="fout" role="alert" style={{ marginBottom: 12 }}>
        AI-maandlimiet bereikt ({status.maand}: € {status.verbruik_eur} van € {status.limiet_eur}) —
        AI-verwerking is geblokkeerd; nieuwe documenten volgen het handmatige pad. Limiet aanpassen kan op
        Instellingen.
      </div>
    )
  }
  return (
    <div className="hint" role="status" style={{ marginBottom: 12, color: 'var(--orange, #b45309)' }}>
      AI-kosten op {status.percentage}% van de maandlimiet ({status.maand}: € {status.verbruik_eur} van €{' '}
      {status.limiet_eur}) — bij 100% wordt AI-verwerking geblokkeerd.
    </div>
  )
}

function somOver(klanten: KlantRij[] | null, kies: (k: KlantRij) => number): number | null {
  if (klanten === null) return null
  return klanten.reduce((som, k) => som + kies(k), 0)
}

function WerkvoorraadIngang({
  administraties,
  filter,
}: {
  administraties: AdministratieDto[]
  filter: string | null
}) {
  const navigate = useNavigate()
  const { klanten, openVragen, fout, herlaad } = useWerkvoorraadData(administraties)
  // Hersleutel voor het verzamelbak-paneel: ophogen forceert een refetch (na .eml-upload).
  const [verzamelbakVersie, setVerzamelbakVersie] = useState(0)
  // Crediteur-dubbelen (v2 03-09, ontwerpnotitie ⑧): kantoorbrede teller uit dezelfde bron als Inzicht ›
  // Crediteuren — verrijking, alleen getoond bij N > 0 (teller-conventie); een fout hier blokkeert niets.
  const [crediteurDubbelen, setCrediteurDubbelen] = useState<number | null>(null)
  useEffect(() => {
    let actueel = true
    haalDubbelenStandOp()
      .then((s) => actueel && setCrediteurDubbelen(s.clusters))
      .catch(() => actueel && setCrediteurDubbelen(null))
    return () => {
      actueel = false
    }
  }, [])

  // Kantoorbrede dwarsdoorsnede (klikbare KPI-kaart) — zelfde databron als de lijst.
  if (filter === 'te_verwerken' || filter === 'vragen' || filter === 'bank' || filter === 'bij_klant') {
    return (
      <FilterWeergave
        filter={filter as WerkvoorraadFilter}
        klanten={klanten}
        klantenFout={fout}
        administraties={administraties}
      />
    )
  }

  const bankBekend = klanten !== null && klanten.some((k) => k.bank_open !== null)
  const ibanWachtend = somOver(klanten, (k) => k.iban_wachtend) ?? 0

  return (
    <div>
      {/* Designpass v2 punt 3: teal-gloed bovenaan — alleen hier (landing), alleen dark. */}
      <Lichtbaan />
      <div className="topbar">
        <div>
          <h1>Werkvoorraad</h1>
          <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
            Alles wat vandaag aandacht vraagt, over alle administraties heen.
          </div>
        </div>
      </div>

      <AiKostenBanner />

      {/* Klikbare KPI's = kantoorbrede dwarsdoorsneden (IA-besluit 15-08: vervangt de losse
          Vragen- en Bank-tabbladen). */}
      <KpiRij
        laden={klanten === null && !fout}
        kaarten={[
          {
            label: 'Te verwerken',
            waarde: somOver(klanten, teVerwerken),
            stipKleur: 'warn',
            delta:
              (somOver(klanten, (k) => k.klaar_om_te_boeken) ?? 0) > 0
                ? `${somOver(klanten, (k) => k.klaar_om_te_boeken)} klaar om te boeken`
                : undefined,
            onClick: () => navigate('/?filter=te_verwerken'),
          },
          {
            // B2.3 (03-09): één definitie mét Inzicht › Open vragen (GET /vragen/stand) — niet meer de som
            // van de klantenlijst-kolom; de delta benoemt hoeveel daarvan de boekknop dichthouden.
            label: 'Open vragen',
            waarde: openVragen?.open ?? null,
            stipKleur: 'danger',
            delta:
              (openVragen?.blokkeert_boeken ?? 0) > 0
                ? openVragen!.blokkeert_boeken === openVragen!.open
                  ? 'blokkeert boeken'
                  : `${openVragen!.blokkeert_boeken} blokkeren boeken`
                : undefined,
            deltaWarn: true,
            onClick: () => navigate('/?filter=vragen'),
          },
          {
            label: 'Bank af te letteren',
            waarde: bankBekend ? somOver(klanten, (k) => k.bank_open ?? 0) : null,
            stipKleur: 'info',
            onClick: () => navigate('/?filter=bank'),
          },
          {
            label: 'Bij klant',
            waarde: somOver(klanten, (k) => k.bij_klant),
            stipKleur: 'purple',
            delta: ibanWachtend > 0 ? `${ibanWachtend} IBAN-accordering wachtend` : undefined,
            deltaWarn: ibanWachtend > 0,
            onClick: () => navigate('/?filter=bij_klant'),
          },
          ...(crediteurDubbelen !== null && crediteurDubbelen > 0
            ? [
                {
                  label: 'Crediteur-dubbelen',
                  waarde: crediteurDubbelen,
                  stipKleur: 'warn' as const,
                  delta: 'voorkeur kiezen, rest archiveren',
                  onClick: () => navigate('/crediteuren'),
                },
              ]
            : []),
        ]}
      />

      <EmlUploadZone onVerwerkt={() => setVerzamelbakVersie((v) => v + 1)} />

      <VerzamelbakPaneel key={verzamelbakVersie} administraties={administraties} onGewijzigd={herlaad} />

      <Klantenlijst klanten={klanten} fout={fout} onHerlaad={herlaad} totaalAdministraties={administraties.length} />
    </div>
  )
}

function EmlUploadZone({ onVerwerkt }: { onVerwerkt: () => void }) {
  const [uploadFout, setUploadFout] = useState<string | null>(null)
  const [uploadBericht, setUploadBericht] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)

  // Werkvoorraad-sleepzone = tenaamstelling-routing (CLAUDE.md): een .eml gaat door de mail-intake,
  // een los bestand (PDF/UBL/foto — punt 2 feedbackronde 25-08 deel 3) door dezelfde routing als een
  // mailbijlage: eenduidige tenaamstelling → klant, twijfel → "Niet toegewezen".
  const uploadBestand = useCallback(async (bestand: File) => {
    setBezig(true)
    setUploadFout(null)
    setUploadBericht(null)
    try {
      if (bestand.name.toLowerCase().endsWith('.eml')) {
        const resultaat = await verwerkEml(bestand)
        setUploadBericht(
          resultaat.al_eerder_verwerkt
            ? `"${bestand.name}" was al eerder verwerkt (zelfde Message-ID) — niets dubbel gedaan.`
            : `"${bestand.name}" verwerkt: ${resultaat.bijlagen
                .map((b) => `${b.bestandsnaam} → ${b.uitkomst.replaceAll('_', ' ')}`)
                .join('; ') || 'geen bijlagen gevonden'}.`,
        )
      } else {
        const r = await verwerkLosBestand(bestand)
        setUploadBericht(`"${bestand.name}" → ${r.uitkomst.replaceAll('_', ' ')}${r.detail ? ` (${r.detail})` : ''}.`)
      }
      onVerwerkt()
    } catch (err) {
      setUploadFout(err instanceof Error ? err.message : 'Verwerken van het bestand is mislukt.')
    } finally {
      setBezig(false)
    }
  }, [onVerwerkt])

  // Punt 3d (27/28-08): één regel + ⓘ-uitleg, zone lager — gedeelde UploadZone.
  return (
    <>
      <UploadZone
        bezig={bezig}
        bezigTekst="Bezig met verwerken…"
        onBestand={(bestand) => void uploadBestand(bestand)}
        regel={
          <>
            Sleep hier een mail (.eml), PDF, UBL of foto naartoe, of <b>blader</b> — toewijzing op tenaamstelling
          </>
        }
        uitleg={
          <>
            Wat eenduidig aan een klant koppelt (tenaamstelling leidend, afzender als hint) gaat direct naar die klant;
            de rest komt in &ldquo;Niet toegewezen&rdquo; hieronder. Een .eml doorloopt de mail-intake (idempotent op
            Message-ID); een foto (JPEG/PNG/HEIC) wordt naar PDF omgezet, het origineel blijft bewaard.
          </>
        }
      />
      {uploadFout && <FoutMelding melding={uploadFout} />}
      {uploadBericht && (
        <div className="hint" style={{ marginTop: -10, marginBottom: 16 }}>
          {uploadBericht}
        </div>
      )}
    </>
  )
}
