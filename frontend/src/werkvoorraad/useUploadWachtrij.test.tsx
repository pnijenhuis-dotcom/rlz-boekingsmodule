import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { KlantUpload } from './KlantStanden'
import { UploadZone } from './UploadZone'

/** Guard bulk-upload component (18-09): de zone accepteert `multiple`, de klantpagina-upload verstuurt N bestanden via de
 * bestaande route (soort voor de hele batch), toont voortgang + samenvatting, 'mogelijk duplicaat' = al aanwezig (geen fout),
 * de lijst ververst precies één keer, en de pagina waarschuwt bij verlaten tijdens de batch. */

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}
const f = (naam: string) => new File(['%PDF'], naam, { type: 'application/pdf' })

afterEach(() => vi.unstubAllGlobals())

describe('UploadZone', () => {
  it('heeft een multiple file-input en geeft álle gekozen bestanden door', async () => {
    const onBestanden = vi.fn()
    render(<UploadZone regel="Sleep" uitleg="u" bezig={false} bezigTekst="b" onBestanden={onBestanden} />)
    const input = screen.getByTestId('upload-input') as HTMLInputElement
    expect(input).toHaveAttribute('multiple')
    await userEvent.upload(input, [f('a.pdf'), f('b.pdf'), f('c.pdf')])
    expect(onBestanden).toHaveBeenCalledTimes(1)
    expect(onBestanden.mock.calls[0][0].map((b: File) => b.name)).toEqual(['a.pdf', 'b.pdf', 'c.pdf'])
  })
})

describe('KlantUpload — batch', () => {
  it('uploadt 6 bestanden mét de gekozen soort, toont voortgang/samenvatting en ververst de lijst één keer', async () => {
    const bodies: FormData[] = []
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      const fd = init?.body as FormData
      bodies.push(fd)
      const naam = (fd.get('bestand') as File).name
      if (naam === 'dubbel.pdf') {
        return json({ document_id: 'd', status: 'ontvangen', mogelijk_duplicaat_van: { document_id: 'x', bestandsnaam: 'orig.pdf', aangemaakt_op: '2026-09-18T10:00:00Z' } }, 201)
      }
      if (naam === 'groot.pdf') return json({ detail: 'Bestand te groot' }, 413)
      return json({ document_id: naam, status: 'extractie_wachtrij', mogelijk_duplicaat_van: null }, 201)
    })
    vi.stubGlobal('fetch', fetchMock)
    const onGeupload = vi.fn()
    render(
      <MemoryRouter>
        <KlantUpload administratieId="adm-1" onGeupload={onGeupload} />
      </MemoryRouter>,
    )
    await userEvent.selectOptions(screen.getByLabelText('Documentsoort voor upload'), 'kassarapport')
    const input = screen.getByTestId('upload-input')
    await act(async () => {
      await userEvent.upload(input, [f('a.pdf'), f('b.pdf'), f('c.pdf'), f('d.pdf'), f('dubbel.pdf'), f('groot.pdf')])
    })
    await waitFor(() => expect(screen.getByTestId('upload-voortgang')).toHaveTextContent('6 aangeboden · 4 nieuw · 1 al aanwezig · 1 fout'))
    expect(fetchMock).toHaveBeenCalledTimes(6)
    expect(bodies.every((fd) => fd.get('soort') === 'kassarapport')).toBe(true)
    expect(onGeupload).toHaveBeenCalledTimes(1)
    const batch = screen.getByTestId('upload-batch')
    expect(batch).toHaveTextContent('al aanwezig als "orig.pdf"')
    expect(batch).toHaveTextContent('te groot')
    // 413 is niet herkansbaar → geen "Mislukte opnieuw"-knop.
    expect(screen.queryByTestId('upload-opnieuw')).not.toBeInTheDocument()
  })

  it('netwerkfout = "Mislukte opnieuw" (alleen die bestanden) en beforeunload-waarschuwing tijdens de batch', async () => {
    let offline = true
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      const naam = ((init?.body as FormData).get('bestand') as File).name
      if (naam === 'b.pdf' && offline) throw new TypeError('Failed to fetch')
      return json({ document_id: naam, status: 'ontvangen', mogelijk_duplicaat_van: null }, 201)
    })
    vi.stubGlobal('fetch', fetchMock)
    const luister = vi.spyOn(window, 'addEventListener')
    const onGeupload = vi.fn()
    render(
      <MemoryRouter>
        <KlantUpload administratieId="adm-1" onGeupload={onGeupload} />
      </MemoryRouter>,
    )
    await act(async () => {
      await userEvent.upload(screen.getByTestId('upload-input'), [f('a.pdf'), f('b.pdf')])
    })
    await waitFor(() => expect(screen.getByTestId('upload-voortgang')).toHaveTextContent('2 aangeboden · 1 nieuw · 1 fout'))
    expect(luister.mock.calls.some(([type]) => type === 'beforeunload')).toBe(true)
    expect(onGeupload).toHaveBeenCalledTimes(1)
    offline = false
    await userEvent.click(screen.getByTestId('upload-opnieuw'))
    await waitFor(() => expect(screen.getByTestId('upload-voortgang')).toHaveTextContent('2 aangeboden · 2 nieuw'))
    // Alleen b.pdf ging opnieuw (3 calls totaal), en de lijst ververste opnieuw ná de herkansing.
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(onGeupload).toHaveBeenCalledTimes(2)
  })
})
