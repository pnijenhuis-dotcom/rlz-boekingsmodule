import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GroepDto } from '../api/types'
import { GroepFilter } from './GroepFilter'

/** Filter "Groep" (blok 8 run 11-09): rendert niets zonder groepen of bij een fout; met groepen een select
 * die de gekozen id teruggeeft (null = alle). */

const KG: GroepDto = { id: 'bbbbbbbb-0000-0000-0000-000000000001', naam: 'Kempen groep', code: 'KEMPENGROEP', actief: true, aantal_administraties: 3 }
const OUD: GroepDto = { id: 'bbbbbbbb-0000-0000-0000-000000000002', naam: 'Oude groep', code: 'OUD', actief: false, aantal_administraties: 0 }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function mockGroepen(groepen: GroepDto[] | null) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (url.startsWith('/groepen')) return Promise.resolve(groepen === null ? new Response(null, { status: 404 }) : jsonResponse({ groepen }))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('GroepFilter', () => {
  it('geen groepen of fout = niets (geen lege select, geen blokkade)', async () => {
    mockGroepen([])
    const { container, unmount } = render(<GroepFilter waarde={null} onWijzig={() => undefined} />)
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
    unmount()
    mockGroepen(null)
    const { container: c2 } = render(<GroepFilter waarde={null} onWijzig={() => undefined} />)
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled())
    expect(c2).toBeEmptyDOMElement()
  })

  it('met groepen: select met "alle" + actieve groepen (ledental), keuze → id, alle → null', async () => {
    mockGroepen([KG, OUD])
    const onWijzig = vi.fn()
    render(<GroepFilter waarde={null} onWijzig={onWijzig} />)
    const select = await screen.findByLabelText('Groep')
    expect(screen.getByRole('option', { name: 'Groep: alle' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Groep: Kempen groep (3)' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Oude groep/ })).not.toBeInTheDocument()
    await userEvent.selectOptions(select, KG.id)
    expect(onWijzig).toHaveBeenLastCalledWith(KG.id)
    await userEvent.selectOptions(select, '')
    expect(onWijzig).toHaveBeenLastCalledWith(null)
  })

  it('een gekozen gearchiveerde groep (deeplink) blijft kiesbaar, gemarkeerd', async () => {
    mockGroepen([KG, OUD])
    render(<GroepFilter waarde={OUD.id} onWijzig={() => undefined} />)
    expect(await screen.findByRole('option', { name: 'Groep: Oude groep (gearchiveerd)' })).toBeInTheDocument()
  })
})
