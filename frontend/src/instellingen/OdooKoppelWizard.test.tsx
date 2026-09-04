import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AdministratieWizard } from './AdministratieWizard'
import { ODOO_KNIP_DEFAULT, OdooKoppelDialog } from './OdooKoppelWizard'

/** Odoo-koppelwizard (adapter blok E 03-09, mockup odoo-koppeling-ui.html §2): één component, twee ingangen.
 * Ingang A = de Odoo-tak van "+ Administratie toevoegen" (backend-keuze stap 1); ingang B = "Odoo koppelen…" op
 * de detailpagina mét expliciete koppelvorm (volledig + overgangsdatum → overstap; leesbron + knip → leesbron).
 * De 422 mét rapport blokkeert (zelfde poort als de RLZ-wizard); de sleutel reist alleen in de body. */

const ADMIN_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const NIEUW_ID = 'cccccccc-0000-0000-0000-000000000003'
const PROBE_OK = { ledgers: 'ok', taxrates: 'ok', vendors: 'ok', journals: 'ok', facturen: 'ok', boeken: 'ok' }

/** Blok A 04-09: mappingvoorstel van POST …/odoo/overstap/voorbereiden — twee grootboekrijen mét voorstel (zelfde
 * code / code + 00), één zonder; één btw-rij mét tarief-voorstel. */
const VOORBEREIDING = {
  company_naam: 'Universal Steigerbouw',
  probe: PROBE_OK,
  grootboek: [
    { rlz_id: 'gb-4699', rlz_code: '4699', rlz_naam: 'Diverse algemene kosten', in_gebruik_observaties: 12, in_gebruik_open_regels: 2, voorstel_odoo_id: 13, voorstel_odoo_code: '4699', voorstel_odoo_naam: 'Diverse algemene kosten', reden: 'zelfde_code' },
    { rlz_id: 'gb-4808', rlz_code: '4808', rlz_naam: 'Huur materieel', in_gebruik_observaties: 40, in_gebruik_open_regels: 0, voorstel_odoo_id: 11, voorstel_odoo_code: '480800', voorstel_odoo_naam: 'Huur materieel', reden: 'code_verlengd' },
    { rlz_id: 'gb-7000', rlz_code: '7000', rlz_naam: 'Inkoop onderaanneming', in_gebruik_observaties: 0, in_gebruik_open_regels: 1, voorstel_odoo_id: null, voorstel_odoo_code: null, voorstel_odoo_naam: null, reden: null },
  ],
  btw: [{ rlz_id: 'btw-hoog', rlz_naam: 'NL, Hoog Tarief', rlz_percentage: '0.21', verlegd: false, in_gebruik_observaties: 30, in_gebruik_open_regels: 3, voorstel_odoo_id: 21, voorstel_odoo_naam: '21% inkoop', reden: 'tarief' }],
  odoo_grootboek: [
    { odoo_id: 11, lokaal_id: '11111111-0000-0000-0000-000000000011', code: '480800', naam: 'Huur materieel' },
    { odoo_id: 12, lokaal_id: '11111111-0000-0000-0000-000000000012', code: '424000', naam: 'Inhuur personeel' },
    { odoo_id: 13, lokaal_id: '11111111-0000-0000-0000-000000000013', code: '4699', naam: 'Diverse algemene kosten' },
  ],
  odoo_btw: [
    { odoo_id: 21, lokaal_id: '22222222-0000-0000-0000-000000000021', naam: '21% inkoop', percentage: '0.21', verlegd: false, synthetisch: false },
    { odoo_id: 0, lokaal_id: '22222222-0000-0000-0000-000000000000', naam: 'Geen btw (0%)', percentage: '0', verlegd: false, synthetisch: true },
  ],
  // Slotstuk 04-09 (blok B): één project mét voorstel op nummer, één zonder voorstel (aan te maken), één zonder nummer (vervalt).
  project: [
    { rlz_id: 'pr-26127', rlz_naam: '26127 Tilburg (Heijmans)', rlz_nummer: '26127', actief: true, in_gebruik_observaties: 8, in_gebruik_open_regels: 1, voorstel_odoo_id: 31, voorstel_odoo_naam: '[26127] Tilburg (Heijmans)', reden: 'projectnummer', kan_aanmaken: true },
    { rlz_id: 'pr-26140', rlz_naam: '26140 Breda (BAM)', rlz_nummer: '26140', actief: true, in_gebruik_observaties: 1, in_gebruik_open_regels: 0, voorstel_odoo_id: null, voorstel_odoo_naam: null, reden: null, kan_aanmaken: true },
    { rlz_id: 'pr-ovh', rlz_naam: 'OVH Overhead', rlz_nummer: null, actief: true, in_gebruik_observaties: 30, in_gebruik_open_regels: 0, voorstel_odoo_id: null, voorstel_odoo_naam: null, reden: null, kan_aanmaken: false },
  ],
  odoo_projecten: [{ odoo_id: 31, lokaal_id: '33333333-0000-0000-0000-000000000031', naam: '[26127] Tilburg (Heijmans)', code: '26127' }],
  telling: { grootboek_totaal: 3, grootboek_met_voorstel: 2, btw_totaal: 1, btw_met_voorstel: 1, project_totaal: 3, project_met_voorstel: 1 },
}
const VOORBEREIDING_LEEG = { ...VOORBEREIDING, grootboek: [], btw: [], project: [], telling: { grootboek_totaal: 0, grootboek_met_voorstel: 0, btw_totaal: 0, btw_met_voorstel: 0, project_totaal: 0, project_met_voorstel: 0 } }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installMock(posts: { url: string; body: unknown }[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
      if (init?.method === 'POST' || init?.method === 'PUT') posts.push({ url, body })
      if (url === '/instellingen/odoo/verbinding-testen') {
        if (body?.api_key === 'fout') return Promise.resolve(jsonResponse({ detail: { bericht: 'Odoo weigert deze sleutel (HTTP 401) — controleer de API-sleutel', rapport: { verbinding: 'HTTP 401' } } }, 422))
        return Promise.resolve(
          jsonResponse({
            companies: [
              { company_id: 1, naam: 'Universal Steigerbouw', al_gekoppeld: false },
              { company_id: 3, naam: 'Universal Verkoop', al_gekoppeld: true },
            ],
          }),
        )
      }
      if (url === '/instellingen/odoo/koppelen') {
        if (body?.api_key === 'rood') {
          return Promise.resolve(
            jsonResponse(
              {
                detail: {
                  bericht: 'Rechten-probe niet groen — niets opgeslagen',
                  rapport: { ...PROBE_OK, boeken: 'geen schrijfrecht op account.move — geef de API-gebruiker boekhoudrechten in Odoo' },
                },
              },
              422,
            ),
          )
        }
        return Promise.resolve(jsonResponse({ administraties: [{ id: NIEUW_ID, naam: 'Universal Steigerbouw', company_id: 1, probe: PROBE_OK, sync_run_id: 'run-1', sync: {} }] }, 201))
      }
      if (url === `/administraties/${ADMIN_ID}/odoo/overstap/voorbereiden`) {
        if (body?.api_key === 'rood') {
          return Promise.resolve(
            jsonResponse(
              { detail: { bericht: 'Rechten-probe niet groen — niets opgeslagen', rapport: { ...PROBE_OK, boeken: 'geen schrijfrecht op account.move — geef de API-gebruiker boekhoudrechten in Odoo' } } },
              422,
            ),
          )
        }
        return Promise.resolve(jsonResponse(body?.api_key === 'leeg' ? VOORBEREIDING_LEEG : VOORBEREIDING))
      }
      if (url === `/administraties/${ADMIN_ID}/odoo/overstap`) {
        const mapping = body?.mapping as { grootboek: unknown[]; btw: unknown[] } | undefined
        if (!mapping) return Promise.resolve(jsonResponse({ detail: [{ loc: ['body', 'mapping'], msg: 'Field required', type: 'missing' }] }, 422))
        if (body?.api_key !== 'leeg' && mapping.grootboek.length + mapping.btw.length < 3) {
          return Promise.resolve(jsonResponse({ detail: { bericht: 'Rekening-mapping onvolledig: 1 grootboekrekening(en) en 0 btw-tarief(en) zonder Odoo-tegenhanger — niets opgeslagen' } }, 422))
        }
        // Slotstuk 04-09: aanmaak-uitkomst per project — één aangemaakt, één overgeslagen mét reden (zichtbaar, nooit stil).
        const project = (mapping as { project?: { aanmaken: boolean }[] }).project ?? []
        const aanmaken = project.filter((r) => r.aanmaken).length
        return Promise.resolve(
          jsonResponse(
            {
              id: ADMIN_ID,
              naam: 'Universal Steigerbouw B.V.',
              company_id: 1,
              probe: PROBE_OK,
              sync_run_id: 'run-2',
              sync: {},
              projecten_aangemaakt: aanmaken,
              projecten_overgeslagen: aanmaken > 0 ? ['26140 Breda (BAM): Odoo weigerde de aanmaak (HTTP 403 op account.analytic.account) — geen analytic-plan-recht'] : [],
            },
            201,
          ),
        )
      }
      if (url === `/administraties/${ADMIN_ID}/odoo/leesbron` && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ groen: true, rapport: { ledgers: 'ok', facturen: 'ok' }, company_naam: 'Universal Steigerbouw', versie: '19.0', lock_dates: {} }, 201))
      }
      if (url.endsWith('/eerste-sync/status')) {
        return Promise.resolve(
          jsonResponse({
            run_id: 'run-1',
            status: 'klaar',
            onderdelen: {
              ledgers: { status: 'klaar', aangemaakt: 212, bijgewerkt: 0 },
              taxrates: { status: 'klaar', aangemaakt: 14, bijgewerkt: 0 },
              vendors: { status: 'klaar', aangemaakt: 380, bijgewerkt: 0 },
              projects: { status: 'klaar', aangemaakt: 0, bijgewerkt: 0 },
            },
            aangevraagd_op: '2026-09-03T20:00:00Z',
            beeindigd_op: '2026-09-03T20:01:00Z',
            fout_reden: null,
          }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

async function vulVerbinding(sleutel = 'geheim') {
  fireEvent.change(screen.getByLabelText('Odoo-URL'), { target: { value: 'https://universal-steigers.odoo.com' } })
  fireEvent.change(screen.getByLabelText('API-sleutel'), { target: { value: sleutel } })
  fireEvent.click(screen.getByRole('button', { name: /Verbinding testen/ }))
  await waitFor(() => expect(screen.getByLabelText('Koppelen Universal Steigerbouw')).toBeInTheDocument())
}

describe('OdooKoppelWizard — ingang A (Odoo-tak van "+ Administratie toevoegen")', () => {
  it('backend-keuze Odoo → verbinding → companies (al gekoppeld uitgeschakeld) → koppelen → resultaat mét eerste sync per Odoo-onderdeel', async () => {
    const posts: { url: string; body: unknown }[] = []
    installMock(posts)
    const onAangemaakt = vi.fn()
    render(<AdministratieWizard open onSluiten={() => {}} onAangemaakt={onAangemaakt} />)

    expect(screen.getByText('Administratie toevoegen — stap 1 van 4')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Odoo'))
    fireEvent.click(screen.getByRole('button', { name: 'Verder →' }))
    expect(screen.getByText('Administratie toevoegen — stap 2 van 4')).toBeInTheDocument()
    // Bewust géén database-veld: de JSON-2-URL bindt de database.
    expect(screen.queryByLabelText(/database/i)).not.toBeInTheDocument()

    await vulVerbinding()
    expect(screen.getByText('Administratie toevoegen — stap 3 van 4')).toBeInTheDocument()
    expect(posts[0]).toEqual({ url: '/instellingen/odoo/verbinding-testen', body: { odoo_url: 'https://universal-steigers.odoo.com', api_key: 'geheim' } })
    expect(screen.getByLabelText('Koppelen Universal Verkoop')).toBeDisabled()
    expect(screen.getByText('al gekoppeld')).toBeInTheDocument()
    // Eén vrije company → alvast aangevinkt; company-id komt uit de lijst, nooit getypt.
    expect(screen.getByLabelText('Koppelen Universal Steigerbouw')).toBeChecked()
    expect(screen.getByText('company 1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Koppeling opslaan \(1\)/ }))
    await waitFor(() => expect(screen.getByText('Administratie toevoegen — stap 4 van 4')).toBeInTheDocument())
    expect(posts.find((p) => p.url === '/instellingen/odoo/koppelen')?.body).toEqual({ odoo_url: 'https://universal-steigers.odoo.com', api_key: 'geheim', company_ids: [1] })
    // Resultaat: company i.p.v. RLZ-id, probe-samenvatting in Odoo-vorm, vier onderdelen (geen bankrekeningen).
    expect(screen.getByText(/company Universal Steigerbouw \(1\)/)).toBeInTheDocument()
    expect(screen.getByText(/Rechten-probe groen: grootboek · btw · relaties · journals · facturen · boeken \(schrijven\)/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/212 nieuw/)).toBeInTheDocument())
    expect(screen.queryByText('Bankrekeningen:')).not.toBeInTheDocument()
    expect(screen.queryByText(/Bankrekeningen/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Sluiten' }))
    expect(onAangemaakt).toHaveBeenCalledTimes(1)
  })

  it('rode rechten-probe (422 mét rapport) blokkeert: foutregel mét handelingsperspectief zichtbaar, wizard blijft op de company-stap, niets aangemaakt', async () => {
    const posts: { url: string; body: unknown }[] = []
    installMock(posts)
    const onAangemaakt = vi.fn()
    render(<AdministratieWizard open onSluiten={() => {}} onAangemaakt={onAangemaakt} />)
    fireEvent.click(screen.getByLabelText('Odoo'))
    fireEvent.click(screen.getByRole('button', { name: 'Verder →' }))
    await vulVerbinding('rood')
    fireEvent.click(screen.getByRole('button', { name: /Koppeling opslaan \(1\)/ }))
    await waitFor(() => expect(screen.getByText(/Rechten-probe niet groen — niets opgeslagen/)).toBeInTheDocument())
    expect(screen.getByText(/geen schrijfrecht op account.move — geef de API-gebruiker boekhoudrechten in Odoo/)).toBeInTheDocument()
    expect(screen.getByText(/Opslaan is geblokkeerd tot de probe groen is/)).toBeInTheDocument()
    expect(screen.getByText('Administratie toevoegen — stap 3 van 4')).toBeInTheDocument()
    expect(screen.queryByTestId('odoo-wizard-resultaat')).not.toBeInTheDocument()
    // Sluiten zónder resultaat = niets aangemaakt → geen herlaad.
    fireEvent.click(screen.getByRole('button', { name: '← Terug' }))
    expect(onAangemaakt).not.toHaveBeenCalled()
  })

  it('sleutel geweigerd bij verbinding testen = leesbare fout op de verbindingsstap', async () => {
    installMock([])
    render(<AdministratieWizard open onSluiten={() => {}} onAangemaakt={() => {}} />)
    fireEvent.click(screen.getByLabelText('Odoo'))
    fireEvent.click(screen.getByRole('button', { name: 'Verder →' }))
    fireEvent.change(screen.getByLabelText('Odoo-URL'), { target: { value: 'https://x.odoo.com' } })
    fireEvent.change(screen.getByLabelText('API-sleutel'), { target: { value: 'fout' } })
    fireEvent.click(screen.getByRole('button', { name: /Verbinding testen/ }))
    await waitFor(() => expect(screen.getByText(/weigert deze sleutel \(HTTP 401\)/)).toBeInTheDocument())
    expect(screen.getByText('Administratie toevoegen — stap 2 van 4')).toBeInTheDocument()
  })
})

describe('OdooKoppelWizard — ingang B (detailpagina "Odoo koppelen…")', () => {
  const administratie = { id: ADMIN_ID, naam: 'Universal Steigerbouw B.V.' }

  it('koppelvorm VOLLEDIG: kanteldatum verplicht, "Verder" = POST …/overstap/voorbereiden → mapping-stap mét voorstel vooringevuld (incl. optioneel projectblok); opslaan pas als grootboek/btw compleet is; POST …/odoo/overstap draagt de mapping mét project-rijen; resultaat toont aangemaakte + overgeslagen projecten', async () => {
    const gebruiker = userEvent.setup()
    const posts: { url: string; body: unknown }[] = []
    installMock(posts)
    const onAfgerond = vi.fn()
    render(<OdooKoppelDialog administratie={administratie} onSluiten={() => {}} onAfgerond={onAfgerond} />)

    expect(screen.getByText('Odoo koppelen — Universal Steigerbouw B.V. — stap 1 van 5')).toBeInTheDocument()
    expect(screen.getByLabelText('Volledige backend')).toBeChecked()
    fireEvent.click(screen.getByRole('button', { name: 'Verder →' }))
    await vulVerbinding()
    expect(screen.getByText('Odoo koppelen — Universal Steigerbouw B.V. — stap 3 van 5')).toBeInTheDocument()
    expect(screen.getByLabelText('Koppelen Universal Steigerbouw')).toHaveAttribute('type', 'radio')
    // Zonder overgangsdatum blijft "Verder" uit (verplicht); er is op deze stap geen opslaan-knop meer.
    expect(screen.queryByRole('button', { name: /Koppeling opslaan/ })).not.toBeInTheDocument()
    const verder = screen.getByRole('button', { name: 'Verder →' })
    expect(verder).toBeDisabled()
    // Slotstuk 04-09: de overgangsdatum is een KANTELDATUM — label + hint zeggen dat nakomers óók in Odoo boeken.
    expect(screen.getByText(/Facturen van vóór deze datum die nog binnenkomen boeken óók in Odoo/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Overgangsdatum (kanteldatum)'), { target: { value: '2026-10-01' } })
    expect(verder).toBeEnabled()
    fireEvent.click(verder)

    // Mapping-stap: voorstel vooringevuld, chips per herkomst, teller, opslaan geblokkeerd tot compleet.
    await waitFor(() => expect(screen.getByTestId('odoo-wizard-mapping')).toBeInTheDocument())
    expect(screen.getByText('Odoo koppelen — Universal Steigerbouw B.V. — stap 4 van 5')).toBeInTheDocument()
    expect(screen.getByText(/kanteldatum 01-10-2026 · 3 Odoo-rekeningen · 2 Odoo-taxen · 1 Odoo-projecten/)).toBeInTheDocument()
    expect(posts.find((p) => p.url === `/administraties/${ADMIN_ID}/odoo/overstap/voorbereiden`)?.body).toEqual({ odoo_url: 'https://universal-steigers.odoo.com', api_key: 'geheim', company_id: 1 })
    // Projecten tellen niet mee in de verplichte teller (3 van 4), wél apart.
    expect(screen.getByTestId('odoo-mapping-teller')).toHaveTextContent('3 van 4 gekoppeld')
    expect(screen.getByTestId('odoo-mapping-projecten-teller')).toHaveTextContent('projecten: 1 van 3 gekoppeld · 2 vervallen')
    expect(within(screen.getByTestId('odoo-mapping-rij-project:pr-26127')).getByText('projectnummer')).toHaveClass('chip', 'ok')
    expect(within(screen.getByTestId('odoo-mapping-rij-grootboek:gb-4699')).getByText('zelfde code')).toHaveClass('chip', 'ok')
    expect(within(screen.getByTestId('odoo-mapping-rij-grootboek:gb-4808')).getByText('code + 00 — bevestig')).toHaveClass('chip', 'afwijking')
    expect(within(screen.getByTestId('odoo-mapping-rij-grootboek:gb-4808')).getByRole('combobox')).toHaveValue('480800 · Huur materieel')
    expect(within(screen.getByTestId('odoo-mapping-rij-grootboek:gb-7000')).getByText('kies')).toHaveClass('chip', 'blokkerend')
    const opslaan = screen.getByRole('button', { name: /Koppeling opslaan/ })
    expect(opslaan).toBeDisabled()
    expect(posts.some((p) => p.url === `/administraties/${ADMIN_ID}/odoo/overstap`)).toBe(false)

    // De ontbrekende rij kiezen → compleet → opslaan mét mapping in de body.
    await gebruiker.click(within(screen.getByTestId('odoo-mapping-rij-grootboek:gb-7000')).getByRole('combobox'))
    await gebruiker.click(screen.getByRole('option', { name: /424000.*Inhuur personeel/ }))
    expect(screen.getByTestId('odoo-mapping-teller')).toHaveTextContent('4 van 4 gekoppeld')
    expect(within(screen.getByTestId('odoo-mapping-rij-grootboek:gb-7000')).getByText('handmatig')).toBeInTheDocument()
    expect(opslaan).toBeEnabled()
    // Project 26140 laten aanmaken in Odoo; OVH blijft leeg (vervalt) — beide houden opslaan niet tegen.
    fireEvent.click(within(screen.getByTestId('odoo-mapping-rij-project:pr-26140')).getByLabelText(/Aanmaken in Odoo: 26140/))
    expect(within(screen.getByTestId('odoo-mapping-rij-project:pr-26140')).getByText('wordt aangemaakt in Odoo')).toHaveClass('chip', 'handmatig')
    expect(screen.getByTestId('odoo-mapping-projecten-teller')).toHaveTextContent('projecten: 1 van 3 gekoppeld · 1 wordt aangemaakt · 1 vervalt')
    expect(opslaan).toBeEnabled()
    fireEvent.click(opslaan)

    await waitFor(() => expect(screen.getByTestId('odoo-wizard-resultaat')).toBeInTheDocument())
    const overstap = posts.find((p) => p.url === `/administraties/${ADMIN_ID}/odoo/overstap`)
    expect(overstap?.body).toEqual({
      odoo_url: 'https://universal-steigers.odoo.com',
      api_key: 'geheim',
      company_id: 1,
      overgangsdatum: '2026-10-01',
      mapping: {
        grootboek: [
          { rlz_id: 'gb-4699', odoo_id: 13 },
          { rlz_id: 'gb-4808', odoo_id: 11 },
          { rlz_id: 'gb-7000', odoo_id: 12 },
        ],
        btw: [{ rlz_id: 'btw-hoog', odoo_id: 21 }],
        project: [
          { rlz_id: 'pr-26127', odoo_id: 31, aanmaken: false },
          { rlz_id: 'pr-26140', odoo_id: null, aanmaken: true },
        ],
      },
    })
    expect(posts.some((p) => p.url.endsWith('/odoo/leesbron'))).toBe(false)
    // Resultaat: aantal aangemaakt + de overgeslagen aanmaak mét serverreden, per regel.
    const projecten = screen.getByTestId('odoo-projecten-resultaat')
    expect(projecten).toHaveTextContent('1 project aangemaakt in Odoo')
    expect(screen.getByTestId('odoo-projecten-overgeslagen')).toHaveTextContent('1 project overgeslagen')
    expect(screen.getByTestId('odoo-projecten-overgeslagen')).toHaveTextContent('26140 Breda (BAM): Odoo weigerde de aanmaak (HTTP 403 op account.analytic.account)')
    fireEvent.click(screen.getByRole('button', { name: 'Sluiten' }))
    expect(onAfgerond).toHaveBeenCalledTimes(1)
  })

  it('koppelvorm VOLLEDIG: rode probe bij voorbereiden (422 mét rapport) = foutregel op de company-stap, geen mapping-stap, niets opgeslagen', async () => {
    const posts: { url: string; body: unknown }[] = []
    installMock(posts)
    render(<OdooKoppelDialog administratie={administratie} onSluiten={() => {}} onAfgerond={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Verder →' }))
    await vulVerbinding('rood')
    fireEvent.change(screen.getByLabelText('Overgangsdatum (kanteldatum)'), { target: { value: '2026-10-01' } })
    fireEvent.click(screen.getByRole('button', { name: 'Verder →' }))
    await waitFor(() => expect(screen.getByText(/Rechten-probe niet groen — niets opgeslagen/)).toBeInTheDocument())
    expect(screen.getByText(/geen schrijfrecht op account.move — geef de API-gebruiker boekhoudrechten in Odoo/)).toBeInTheDocument()
    expect(screen.getByText('Odoo koppelen — Universal Steigerbouw B.V. — stap 3 van 5')).toBeInTheDocument()
    expect(screen.queryByTestId('odoo-wizard-mapping')).not.toBeInTheDocument()
    expect(posts.some((p) => p.url === `/administraties/${ADMIN_ID}/odoo/overstap`)).toBe(false)
  })

  it('koppelvorm VOLLEDIG zonder in-gebruik-rijen: mapping-stap toont "mapping niet nodig" en opslaan kan direct mét lege mapping', async () => {
    const posts: { url: string; body: unknown }[] = []
    installMock(posts)
    render(<OdooKoppelDialog administratie={administratie} onSluiten={() => {}} onAfgerond={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Verder →' }))
    await vulVerbinding('leeg')
    fireEvent.change(screen.getByLabelText('Overgangsdatum (kanteldatum)'), { target: { value: '2026-10-01' } })
    fireEvent.click(screen.getByRole('button', { name: 'Verder →' }))
    await waitFor(() => expect(screen.getByTestId('odoo-mapping-leeg')).toBeInTheDocument())
    expect(screen.getByTestId('odoo-mapping-leeg')).toHaveTextContent('Geen boekingsgeheugen of open regels om te vertalen — mapping niet nodig.')
    const opslaan = screen.getByRole('button', { name: /Koppeling opslaan/ })
    expect(opslaan).toBeEnabled()
    fireEvent.click(opslaan)
    await waitFor(() => expect(screen.getByTestId('odoo-wizard-resultaat')).toBeInTheDocument())
    expect(posts.find((p) => p.url === `/administraties/${ADMIN_ID}/odoo/overstap`)?.body).toMatchObject({ mapping: { grootboek: [], btw: [], project: [] } })
    // Niets aangemaakt/overgeslagen = geen projectenblok op het resultaat.
    expect(screen.queryByTestId('odoo-projecten-resultaat')).not.toBeInTheDocument()
  })

  it('koppelvorm LEESBRON: knipdatum-stap mét default 2026-09-01, "Koppeling opslaan" = POST …/odoo/leesbron mét knip; resultaat toont de leesprobe', async () => {
    const posts: { url: string; body: unknown }[] = []
    installMock(posts)
    render(<OdooKoppelDialog administratie={administratie} onSluiten={() => {}} onAfgerond={() => {}} />)

    fireEvent.click(screen.getByLabelText('Alleen-lezen leesbron'))
    fireEvent.click(screen.getByRole('button', { name: 'Verder →' }))
    expect(screen.getByText('Odoo koppelen — Universal Steigerbouw B.V. — stap 2 van 5')).toBeInTheDocument()
    await vulVerbinding()
    // Leesbron: geen overgangsdatum, wél een knipdatum-stap.
    expect(screen.queryByLabelText(/Overgangsdatum/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Knipdatum kiezen →' }))
    const knip = screen.getByLabelText('Knipdatum voorraad-uitstroom') as HTMLInputElement
    expect(knip.value).toBe(ODOO_KNIP_DEFAULT)
    expect(ODOO_KNIP_DEFAULT).toBe('2026-09-01')
    fireEvent.click(screen.getByRole('button', { name: /Koppeling opslaan/ }))

    await waitFor(() => expect(screen.getByTestId('odoo-wizard-resultaat')).toBeInTheDocument())
    const leesbron = posts.find((p) => p.url === `/administraties/${ADMIN_ID}/odoo/leesbron`)
    expect(leesbron?.body).toEqual({ odoo_url: 'https://universal-steigers.odoo.com', api_key: 'geheim', company_id: 1, voorraad_knip_datum: '2026-09-01' })
    expect(posts.some((p) => p.url.endsWith('/odoo/overstap'))).toBe(false)
    expect(screen.getByText('leesbron gekoppeld')).toBeInTheDocument()
    expect(screen.getByText(/verkoop-uitstroom vanaf 01-09-2026/)).toBeInTheDocument()
  })
})
