import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { Button, Switch } from '../ui/basis'
import { BevestigDialog } from './BevestigDialog'
import {
  haalAppUpdateBundels,
  haalAppUpdateInstelling,
  haalAppUpdateToestellen,
  zetAppUpdateBundelActief,
  zetAppUpdateInstelling,
  type AppUpdateBundelDto,
  type AppUpdateInstellingDto,
  type AppUpdateToestelDto,
} from './instellingenApi'

/** Instellingen › Boeken platformbreed — blok "App-updates" (OTA, besluit Peter 16-09): huidige bundels per runtime
 * (nieuwste eerst, terugtrekken = deactiveren), cohort-percentage, kill-switch (DB; de env-noodrem staat er als stand bij)
 * en de laatste 20 toestellen mét de bundel die ze meldden. Beheerder-only, audit server-side. */
export function AppUpdatesBlok() {
  const [instelling, setInstelling] = useState<AppUpdateInstellingDto | null>(null)
  const [bundels, setBundels] = useState<AppUpdateBundelDto[]>([])
  const [toestellen, setToestellen] = useState<AppUpdateToestelDto[]>([])
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [pending, setPending] = useState<{ omschrijving: string; uitvoeren: () => Promise<void> } | null>(null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [percentageInvoer, setPercentageInvoer] = useState('')

  const laad = () => {
    Promise.all([haalAppUpdateInstelling(), haalAppUpdateBundels(), haalAppUpdateToestellen()])
      .then(([i, b, t]) => {
        setInstelling(i)
        setPercentageInvoer(String(i.percentage))
        setBundels(b)
        setToestellen(t)
      })
      .catch((err: unknown) => setLaadFout(err instanceof ApiError ? err.message : 'App-updates niet beschikbaar.'))
  }
  useEffect(laad, [])

  const bevestigen = async () => {
    if (!pending) return
    setBezig(true)
    setFout(null)
    try {
      await pending.uitvoeren()
      setPending(null)
      laad()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Wijzigen mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  const perRuntime = new Map<string, AppUpdateBundelDto>()
  for (const b of bundels) if (b.actief && !perRuntime.has(b.runtime)) perRuntime.set(b.runtime, b)

  return (
    <div id="app-updates" data-testid="app-updates" style={{ marginTop: 18, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
      <h2 style={{ margin: 0 }}>App-updates (accordeur-/veldwerker-app)</h2>
      <p className="hint" style={{ marginTop: 4 }}>
        De app werkt haar schermen zelf bij: bij het openen haalt ze de nieuwste webbundel voor haar versie op en past die bij
        de volgende start toe. Native wijzigingen (plugins, rechten) blijven een winkelrelease. Hier zie je welke bundel per
        app-versie actief is, hoeveel toestellen meedoen (cohort) en de noodrem.
      </p>
      {laadFout && (
        <span className="text-[12px] text-orange" role="alert">
          {laadFout}
        </span>
      )}
      {instelling && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center', margin: '10px 0' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
            <Switch
              aria-label="Live updates uitgeschakeld (noodrem)"
              checked={instelling.uitgeschakeld}
              onChange={(e) => {
                const uit = e.target.checked
                setPending({
                  omschrijving: uit
                    ? 'Live updates worden UITGEZET: elke app krijgt "geen update" en valt terug op de ingebouwde bundel uit de winkel-build.'
                    : 'Live updates worden weer AANGEZET: apps halen bij het openen de nieuwste bundel voor hun versie op.',
                  uitvoeren: async () => {
                    await zetAppUpdateInstelling({ uitgeschakeld: uit })
                  },
                })
              }}
            />
            {instelling.uitgeschakeld ? 'noodrem AAN — geen updates' : 'updates aan'}
            {instelling.env_uitgeschakeld && (
              <span className="chip vraag" title="OTA_UITGESCHAKELD=true in de deploy — alleen daar weer uit te zetten">
                env-noodrem aan
              </span>
            )}
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
            Cohort
            <input
              aria-label="Cohort-percentage"
              type="number"
              min={0}
              max={100}
              value={percentageInvoer}
              onChange={(e) => setPercentageInvoer(e.target.value)}
              style={{ width: 64 }}
            />
            %
            <Button
              variant="secundair"
              maat="klein"
              disabled={percentageInvoer === String(instelling.percentage)}
              onClick={() => {
                const p = Number(percentageInvoer)
                if (!Number.isInteger(p) || p < 0 || p > 100) {
                  setFout('Percentage moet een geheel getal tussen 0 en 100 zijn.')
                  return
                }
                setPending({
                  omschrijving: `Het cohort wordt ${p} %: alleen dat deel van de toestellen krijgt de nieuwe bundel (deterministisch per toestel); 100 % = iedereen.`,
                  uitvoeren: async () => {
                    await zetAppUpdateInstelling({ percentage: p })
                  },
                })
              }}
            >
              Opslaan
            </Button>
          </label>
          <span className="hint" style={{ margin: 0 }}>
            minimale app-versie: <b>{instelling.min_runtime_versie}</b> (schil eronder krijgt &ldquo;Update nodig&rdquo;)
          </span>
        </div>
      )}
      {fout && (
        <span className="text-[12px] text-orange" role="alert">
          {fout}
        </span>
      )}
      <h3 style={{ fontSize: 14, margin: '12px 0 6px' }}>Bundels ({bundels.length})</h3>
      {bundels.length === 0 ? (
        <p className="hint">Nog geen bundel geregistreerd — de eerstvolgende deploy registreert er één per app-versie.</p>
      ) : (
        <div className="tabel-scroll">
          <table className="lines">
            <tbody>
              <tr>
                <th>App-versie</th>
                <th>Bundel</th>
                <th>Platform</th>
                <th>Gebouwd</th>
                <th>Stand</th>
                <th></th>
              </tr>
              {bundels.map((b) => (
                <tr key={b.bundel_id}>
                  <td>{b.runtime}</td>
                  <td>
                    <code>{b.bundel_id}</code>
                    {b.verplicht && <span className="chip vraag" style={{ marginLeft: 6 }}>verplicht</span>}
                  </td>
                  <td>{b.platform}</td>
                  <td>{b.aangemaakt_op.slice(0, 16).replace('T', ' ')}</td>
                  <td>
                    {perRuntime.get(b.runtime)?.bundel_id === b.bundel_id ? (
                      <span className="chip ok">actief — wordt uitgedeeld</span>
                    ) : b.actief ? (
                      'ouder'
                    ) : (
                      <span className="chip">teruggetrokken</span>
                    )}
                  </td>
                  <td>
                    <Button
                      variant="secundair"
                      maat="klein"
                      onClick={() =>
                        setPending({
                          omschrijving: b.actief
                            ? `Bundel ${b.bundel_id} wordt teruggetrokken: nieuwe toestellen krijgen de vorige actieve bundel van versie ${b.runtime}; toestellen die 'm al hebben blijven 'm draaien tot de volgende update.`
                            : `Bundel ${b.bundel_id} wordt weer beschikbaar gemaakt.`,
                          uitvoeren: async () => {
                            await zetAppUpdateBundelActief(b.bundel_id, !b.actief)
                          },
                        })
                      }
                    >
                      {b.actief ? 'Terugtrekken…' : 'Herstellen…'}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h3 style={{ fontSize: 14, margin: '12px 0 6px' }}>Laatste toestellen ({toestellen.length})</h3>
      {toestellen.length === 0 ? (
        <p className="hint">Nog geen toestel heeft zijn versie gemeld (dat doet de app vanaf de eerste versie mét live updates).</p>
      ) : (
        <div className="tabel-scroll">
          <table className="lines">
            <tbody>
              <tr>
                <th>Toestel</th>
                <th>Platform</th>
                <th>App-versie</th>
                <th>Bundel</th>
                <th>Gezien</th>
              </tr>
              {toestellen.map((t) => (
                <tr key={t.apparaat_id}>
                  <td>{t.apparaat_naam ?? '—'}</td>
                  <td>{t.platform ?? '—'}</td>
                  <td>{t.app_versie ?? '—'}</td>
                  <td>
                    <code>{t.bundel_id ?? '—'}</code>
                  </td>
                  <td>{(t.bundel_gezien_op ?? t.laatst_gebruikt_op ?? '').slice(0, 16).replace('T', ' ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pending && (
        <BevestigDialog
          titel="App-updates wijzigen?"
          bericht={`${pending.omschrijving} Geauditeerd.`}
          bezig={bezig}
          fout={fout}
          onBevestigen={() => void bevestigen()}
          onAnnuleren={() => {
            setFout(null)
            setPending(null)
          }}
        />
      )}
    </div>
  )
}
