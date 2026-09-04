import { useEffect, useState } from 'react'
import type { AdministratieDto } from '../api/types'
import { ApiError } from '../api/client'
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  FormField,
  MultiSelect,
  Select,
} from '../ui/basis'
import { nodigUit, type UitnodigingBron, type UitnodigingResultaatDto } from './gebruikersApi'

type Soort = 'medewerker' | 'accordeur' | 'veldwerker'

/** Rolgroep per ingang (bugfix 04-09): de soort van de dialoog bepaalt welke rollen überhaupt verstuurd kunnen
 * worden — nooit een stille kantoor-default over tabs heen. Spiegel van `toets_rolgroep_bij_bron` (backend). */
export const ROLGROEPEN: Record<Soort, { rollen: readonly string[]; standaard: string; bron: UitnodigingBron; label: string }> = {
  medewerker: {
    rollen: ['boekhouding', 'boekhouding_projecten', 'beheerder'],
    standaard: 'boekhouding',
    bron: 'kantoor',
    label: 'Kantoormedewerker (Boekhouding · Boekhouding + Projecten · Beheerder)',
  },
  veldwerker: {
    rollen: ['zzper', 'uitvoerder', 'detacheerder'],
    standaard: 'zzper',
    bron: 'veldwerkers',
    label: "Veldwerker (ZZP'er · Uitvoerder · Detacheerder) — mobiele app",
  },
  accordeur: {
    rollen: ['klant_accordeur'],
    standaard: 'klant_accordeur',
    bron: 'klant_accordeurs',
    label: 'Klant-accordeur — mobiele app',
  },
}

/** Fail-safe vóór verzenden: een rol buiten de rolgroep van de ingang valt terug op de standaard van die groep. */
export function rolBinnenGroep(soort: Soort, rol: string): string {
  const groep = ROLGROEPEN[soort]
  return groep.rollen.includes(rol) ? rol : groep.standaard
}

/* Uitnodig-modal (mockup #modal medewerker/accordeur, fase 3 15-08) — op de bestaande
 * uitnodigingsflow (POST /auth/uitnodigingen, mailt al; fail-zichtbaar bij een mailfout).
 * Bugfix 04-09 (casus Peter: "+ Veldwerker uitnodigen" maakte een kantoormedewerker aan): de rol volgt de
 * SOORT van de ingang — reset bij elke soortwissel, rolgroep expliciet in de dialoog, fail-safe bij verzenden
 * én `bron` naar de server (die weigert een mismatch met 422). */
export function UitnodigModal({
  soort,
  administraties,
  open,
  onSluiten,
  onUitgenodigd,
}: {
  soort: Soort
  administraties: AdministratieDto[]
  open: boolean
  onSluiten: () => void
  onUitgenodigd: (resultaat: UitnodigingResultaatDto) => void
}) {
  const [naam, setNaam] = useState('')
  const [eMail, setEMail] = useState('')
  const [rol, setRol] = useState(ROLGROEPEN[soort].standaard)
  // De useState-initializer draait maar één keer — wisselt de ingang (tab) terwijl de dialoog gemount blijft,
  // dan moet de rol de nieuwe rolgroep volgen (dát was de bug: 'boekhouding' bleef staan onder "Veldwerker").
  useEffect(() => {
    setRol(ROLGROEPEN[soort].standaard)
  }, [soort])
  const [scope, setScope] = useState<string[]>([])
  // A4 (25-08): veldwerker aanmaken zónder mail — account op 'uitgenodigd', alsnog mailen via
  // de bestaande "Opnieuw mailen"-knop op Gebruikers & toegang.
  const [uitnodigingLater, setUitnodigingLater] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const isAccordeur = soort === 'accordeur'
  const isVeldwerker = soort === 'veldwerker'
  const scopeVerplicht = isAccordeur || isVeldwerker || rol !== 'beheerder'

  async function verstuur() {
    setBezig(true)
    setFout(null)
    try {
      const resultaat = await nodigUit({
        naam: naam.trim(),
        e_mail: eMail.trim(),
        rol: rolBinnenGroep(soort, rol),
        administratie_ids: scope,
        uitnodiging_later: isVeldwerker && uitnodigingLater,
        bron: ROLGROEPEN[soort].bron,
      })
      onUitgenodigd(resultaat)
      setNaam('')
      setEMail('')
      setScope([])
      setUitnodigingLater(false)
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Uitnodigen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const kanVersturen = naam.trim() !== '' && eMail.trim().includes('@') && (!scopeVerplicht || scope.length > 0)

  return (
    <Dialog open={open} onOpenChange={(nieuwOpen) => !nieuwOpen && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>
          {isAccordeur ? 'Accordeur uitnodigen' : isVeldwerker ? 'Veldwerker uitnodigen' : 'Medewerker uitnodigen'}
        </DialogTitle>
        <DialogDescription>
          {isAccordeur
            ? 'De accordeur krijgt een activatiemail voor de mobiele app (wachtwoord → passkey → voorwaarden). Meerdere administraties mag — de wachtrij toont alles bij elkaar.'
            : isVeldwerker
              ? "Veldwerkers (uren & meerwerk) gebruiken dezelfde mobiele app en passkey-flow als de accordeurs. Ná activatie koppel je projecten (ZZP'er/uitvoerder) of ZZP'ers (detacheerder) in dit scherm."
              : 'De uitnodiging wordt gemaild (eenmalige link, 72 uur geldig). Activatie = wachtwoord + tweede factor.'}
        </DialogDescription>
        <p className="hint" data-testid="uitnodig-rolgroep" style={{ marginTop: 0 }}>
          <b>Rolgroep:</b> {ROLGROEPEN[soort].label}
        </p>
        <FormField label="Naam" htmlFor="uitnodig-naam">
          <input
            id="uitnodig-naam"
            type="text"
            value={naam}
            onChange={(e) => setNaam(e.target.value)}
            placeholder={isAccordeur ? 'R. de Groot' : 'Voor- en achternaam'}
          />
        </FormField>
        <FormField label="E-mailadres" htmlFor="uitnodig-email">
          <input
            id="uitnodig-email"
            type="email"
            value={eMail}
            onChange={(e) => setEMail(e.target.value)}
            placeholder={isAccordeur ? 'naam@klantbedrijf.nl' : 'naam@ak-nijenhuis.nl'}
          />
        </FormField>
        {isVeldwerker && (
          <FormField
            label="Rol"
            htmlFor="uitnodig-rol"
            hint="ZZP'er: weekstaten per project · Uitvoerder: keurt weekstaten per week + meldt meerwerk · Detacheerder: vult in namens gekoppelde ZZP'ers"
          >
            <Select id="uitnodig-rol" className="w-full" value={rol} onChange={(e) => setRol(e.target.value)}>
              <option value="zzper">ZZP'er</option>
              <option value="uitvoerder">Uitvoerder</option>
              <option value="detacheerder">Detacheerder</option>
            </Select>
          </FormField>
        )}
        {!isAccordeur && !isVeldwerker && (
          <FormField
            label="Rol"
            htmlFor="uitnodig-rol"
            hint="Boekhouding: verwerken & boeken · +Projecten: ook projectbewaking · Beheerder: alles incl. instellingen en gebruikersbeheer"
          >
            <Select id="uitnodig-rol" className="w-full" value={rol} onChange={(e) => setRol(e.target.value)}>
              <option value="boekhouding">Boekhouding</option>
              <option value="boekhouding_projecten">Boekhouding + Projecten</option>
              <option value="beheerder">Beheerder</option>
            </Select>
          </FormField>
        )}
        <FormField
          label={isAccordeur ? 'Administraties' : 'Administratie-scope'}
          hint={
            rol === 'beheerder' && !isAccordeur && !isVeldwerker
              ? 'Een Beheerder is platform-breed — scope is niet nodig.'
              : isAccordeur
                ? 'Minstens één — de wachtrij voegt alles samen.'
                : isVeldwerker
                  ? 'Minstens één — de administratie(s) met de uren-&-meerwerk-opt-in (Universal).'
                  : 'Minstens één — zonder scope ziet iemand niets.'
          }
        >
          {/* D3 (besluit Peter 25-08): alles/geen naast de losse vinkjes — bij 11+ administraties
              is per stuk aanvinken onnodig klikwerk voor een kantoormedewerker. */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
            <Button
              type="button"
              variant="secundair"
              maat="klein"
              disabled={scope.length === administraties.length}
              onClick={() => setScope(administraties.map((a) => a.id))}
            >
              Alle administraties selecteren
            </Button>
            <Button type="button" variant="ghost" maat="klein" disabled={scope.length === 0} onClick={() => setScope([])}>
              Geen
            </Button>
            <span className="hint" style={{ margin: 0, alignSelf: 'center' }}>
              {scope.length} van {administraties.length} geselecteerd
            </span>
          </div>
          <MultiSelect
            opties={administraties.map((a) => ({ waarde: a.id, label: a.naam }))}
            waarden={scope}
            onChange={setScope}
            zoekPlaceholder="Zoek administratie… (typ om te filteren)"
          />
        </FormField>
        {isAccordeur && (
          <p className="hint" style={{ marginTop: 0 }}>
            Accorderingslagen en drempels stel je per administratie in onder Instellingen → accordering.
          </p>
        )}
        {isVeldwerker && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, marginBottom: 10 }}>
            <Checkbox checked={uitnodigingLater} onChange={(e) => setUitnodigingLater(e.target.checked)} />
            <span>
              <b>Uitnodiging later versturen</b> — het account wordt nu aangemaakt (status uitgenodigd) zonder mail; alsnog
              uitnodigen kan met "Opnieuw mailen".
            </span>
          </label>
        )}
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button onClick={() => void verstuur()} disabled={bezig || !kanVersturen}>
            {bezig ? 'Bezig…' : isVeldwerker && uitnodigingLater ? 'Account aanmaken (zonder mail)' : 'Verstuur uitnodiging'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
