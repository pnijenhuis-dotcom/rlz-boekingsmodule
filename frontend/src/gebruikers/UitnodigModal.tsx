import { useState } from 'react'
import type { AdministratieDto } from '../api/types'
import { ApiError } from '../api/client'
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  FormField,
  MultiSelect,
  Select,
} from '../ui/basis'
import { nodigUit, type UitnodigingResultaatDto } from './gebruikersApi'

/* Uitnodig-modal (mockup #modal medewerker/accordeur, fase 3 15-08) — op de bestaande
 * uitnodigingsflow (POST /auth/uitnodigingen, mailt al; fail-zichtbaar bij een mailfout). */
export function UitnodigModal({
  soort,
  administraties,
  open,
  onSluiten,
  onUitgenodigd,
}: {
  soort: 'medewerker' | 'accordeur' | 'veldwerker'
  administraties: AdministratieDto[]
  open: boolean
  onSluiten: () => void
  onUitgenodigd: (resultaat: UitnodigingResultaatDto) => void
}) {
  const [naam, setNaam] = useState('')
  const [eMail, setEMail] = useState('')
  const [rol, setRol] = useState(
    soort === 'accordeur' ? 'klant_accordeur' : soort === 'veldwerker' ? 'zzper' : 'boekhouding',
  )
  const [scope, setScope] = useState<string[]>([])
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
        rol: isAccordeur ? 'klant_accordeur' : rol,
        administratie_ids: scope,
      })
      onUitgenodigd(resultaat)
      setNaam('')
      setEMail('')
      setScope([])
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
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button onClick={() => void verstuur()} disabled={bezig || !kanVersturen}>
            {bezig ? 'Bezig…' : 'Verstuur uitnodiging'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
