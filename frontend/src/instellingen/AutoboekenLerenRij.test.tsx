// Schakelaar "Autoboeken (leren en boeken)" per administratie (blok A bundel 10-09): aan/uit via bevestigingsdialoog
// + PUT, Kempen-regel (toegestaan=false → switch disabled + rode hint; 409 op de PUT → dialoog dicht + hint),
// gearchiveerd = disabled, onGewijzigd ná een geslaagde PUT (herlaad lijst).
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AutoboekenLerenRij } from './AutoboekenLerenRij'
import { AUTOBOEKEN_LEREN_NIET_TOEGESTAAN_TEKST } from './instellingenApi'

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installFetch(opties: { stand?: Record<string, unknown>; putStatus?: number; puts?: { url: string; body: unknown }[] } = {}) {
  const stand = { ingeschakeld: false, toegestaan: true, reden_niet_toegestaan: null, ...opties.stand }
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url === `/administraties/${ADM}/autoboeken-leren-instelling` && (!init?.method || init.method === 'GET')) return Promise.resolve(json(stand))
      if (url === `/administraties/${ADM}/autoboeken-leren-instelling` && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { ingeschakeld: boolean }
        opties.puts?.push({ url, body })
        if (opties.putStatus === 409) return Promise.resolve(json({ detail: AUTOBOEKEN_LEREN_NIET_TOEGESTAAN_TEKST }, 409))
        if (opties.putStatus && opties.putStatus >= 400) return Promise.resolve(json({ detail: 'Alleen een Beheerder mag dit wijzigen.' }, opties.putStatus))
        return Promise.resolve(json({ ...stand, ingeschakeld: body.ingeschakeld }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

describe('AutoboekenLerenRij — schakelaar per administratie (blok A 10-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('laadt de stand, toont de uitlegregel en zet aan via bevestiging → PUT {ingeschakeld:true} → onGewijzigd', async () => {
    const puts: { url: string; body: unknown }[] = []
    installFetch({ puts })
    const onGewijzigd = vi.fn()
    const gebruiker = userEvent.setup()
    render(<AutoboekenLerenRij administratieId={ADM} naam="Testklant B.V." onGewijzigd={onGewijzigd} />)
    expect(screen.getByText('Het systeem activeert een leverancier ná 3 identieke boekingen op rij; hieronder alleen uitzonderingen.')).toBeInTheDocument()
    const sw = screen.getByRole('checkbox', { name: 'Autoboeken (leren en boeken) voor Testklant B.V.' })
    await waitFor(() => expect(sw).toBeEnabled())
    expect(sw).not.toBeChecked()
    await gebruiker.click(sw)
    expect(screen.getByRole('dialog')).toHaveTextContent('3 op rij exact hetzelfde boekt')
    expect(puts).toHaveLength(0)
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(puts).toEqual([{ url: `/administraties/${ADM}/autoboeken-leren-instelling`, body: { ingeschakeld: true } }])
    expect(sw).toBeChecked()
    expect(screen.getByText('aan')).toBeInTheDocument()
    expect(onGewijzigd).toHaveBeenCalledWith(expect.objectContaining({ ingeschakeld: true }))
  })

  it('uitzetten: kortere tekst, PUT {ingeschakeld:false}; annuleren = geen PUT', async () => {
    const puts: { url: string; body: unknown }[] = []
    installFetch({ stand: { ingeschakeld: true }, puts })
    const gebruiker = userEvent.setup()
    render(<AutoboekenLerenRij administratieId={ADM} naam="Testklant B.V." />)
    const sw = screen.getByRole('checkbox', { name: 'Autoboeken (leren en boeken) voor Testklant B.V.' })
    await waitFor(() => expect(sw).toBeChecked())
    await gebruiker.click(sw)
    expect(screen.getByRole('dialog')).toHaveTextContent('het systeem activeert geen leveranciers meer')
    await gebruiker.click(screen.getByRole('button', { name: 'Annuleren' }))
    expect(puts).toHaveLength(0)
    expect(sw).toBeChecked()
    await gebruiker.click(sw)
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(puts).toEqual([expect.objectContaining({ body: { ingeschakeld: false } })]))
    await waitFor(() => expect(sw).not.toBeChecked())
  })

  it('Kempen-regel vooraf (toegestaan=false): switch disabled + rode hint met de 409-tekst', async () => {
    installFetch({ stand: { toegestaan: false, reden_niet_toegestaan: AUTOBOEKEN_LEREN_NIET_TOEGESTAAN_TEKST } })
    render(<AutoboekenLerenRij administratieId={ADM} naam="Kempen Facilities B.V." />)
    expect(await screen.findByTestId('autoboeken-leren-hint')).toHaveTextContent(AUTOBOEKEN_LEREN_NIET_TOEGESTAAN_TEKST)
    expect(screen.getByRole('checkbox', { name: 'Autoboeken (leren en boeken) voor Kempen Facilities B.V.' })).toBeDisabled()
  })

  it('409 op de PUT (doorbelasting ingeschakeld ná het laden): dialoog dicht, hint met de servertekst, switch blijft uit en disabled, geen onGewijzigd', async () => {
    installFetch({ putStatus: 409 })
    const onGewijzigd = vi.fn()
    const gebruiker = userEvent.setup()
    render(<AutoboekenLerenRij administratieId={ADM} naam="Kempen Facilities B.V." onGewijzigd={onGewijzigd} />)
    const sw = screen.getByRole('checkbox', { name: 'Autoboeken (leren en boeken) voor Kempen Facilities B.V.' })
    await waitFor(() => expect(sw).toBeEnabled())
    await gebruiker.click(sw)
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    expect(await screen.findByTestId('autoboeken-leren-hint')).toHaveTextContent('doorbelast kosten aan andere entiteiten')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(sw).not.toBeChecked()
    expect(sw).toBeDisabled()
    expect(onGewijzigd).not.toHaveBeenCalled()
  })

  it('andere fout (403) blijft in de dialoog staan; gearchiveerd = disabled', async () => {
    installFetch({ putStatus: 403 })
    const gebruiker = userEvent.setup()
    const { unmount } = render(<AutoboekenLerenRij administratieId={ADM} naam="Testklant B.V." />)
    const sw = screen.getByRole('checkbox', { name: 'Autoboeken (leren en boeken) voor Testklant B.V.' })
    await waitFor(() => expect(sw).toBeEnabled())
    await gebruiker.click(sw)
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    expect(await screen.findByText('Alleen een Beheerder mag dit wijzigen.')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    unmount()
    installFetch({})
    render(<AutoboekenLerenRij administratieId={ADM} naam="Oud B.V." uitgeschakeld />)
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled())
    expect(screen.getByRole('checkbox', { name: 'Autoboeken (leren en boeken) voor Oud B.V.' })).toBeDisabled()
  })
})
