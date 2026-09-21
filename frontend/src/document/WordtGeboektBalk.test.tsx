import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StatusChip } from '../werkvoorraad/StatusChip'
import { opnieuwIndienenMelding, WordtGeboektBalk } from './WordtGeboektBalk'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const T0 = Date.parse('2026-09-21T12:46:00Z')

describe('WordtGeboektBalk + StatusChip loopt-vast (BUG 21-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('StatusChip: ná 5 min "loopt vast" mét oranje dot, daarvóór de gewone stip', () => {
    const { rerender } = render(<StatusChip status="wordt_geboekt" laatstGewijzigdOp="2026-09-21T12:46:00Z" nu={T0 + 60_000} />)
    expect(screen.getByText('Wordt geboekt…')).not.toHaveAttribute('data-loopt-vast')
    rerender(<StatusChip status="wordt_geboekt" laatstGewijzigdOp="2026-09-21T12:46:00Z" nu={T0 + 16 * 60_000} />)
    const chip = screen.getByText('Wordt geboekt… (loopt vast — 16 min)')
    expect(chip).toHaveAttribute('data-loopt-vast', '1')
    expect(chip.className).toContain('vraag')
    // Andere statussen ongewijzigd.
    rerender(<StatusChip status="geboekt" laatstGewijzigdOp="2026-09-21T12:46:00Z" nu={T0 + 16 * 60_000} />)
    expect(screen.getByText('Geboekt').className).toContain('geboekt')
  })

  it('binnen de grens: informatieve balk zonder knop', () => {
    render(
      <WordtGeboektBalk administratieId="adm-1" documentId="doc-1" laatstGewijzigdOp="2026-09-21T12:46:00Z" onOpnieuw={vi.fn()} nu={T0 + 60_000} />,
    )
    expect(screen.getByTestId('wordt-geboekt-balk')).toHaveTextContent('Wordt geboekt…')
    expect(screen.queryByRole('button', { name: 'Boeking opnieuw indienen' })).toBeNull()
  })

  it('loopt vast: knop "Opnieuw indienen" → POST op de documentroute, melding mét trigger-uitkomst', async () => {
    const aanroepen: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        aanroepen.push(`${init?.method ?? 'GET'} ${url}`)
        return Promise.resolve(
          jsonResponse({ document_id: 'doc-1', status: 'wordt_geboekt', sleutel: 'boek-doc-1-0', trigger_uitkomst: 'geslaagd', trigger_fout: null }),
        )
      }),
    )
    const onOpnieuw = vi.fn()
    render(
      <WordtGeboektBalk administratieId="adm-1" documentId="doc-1" laatstGewijzigdOp="2026-09-21T12:46:00Z" onOpnieuw={onOpnieuw} nu={T0 + 16 * 60_000} />,
    )
    expect(screen.getByTestId('wordt-geboekt-balk')).toHaveTextContent('loopt vast')
    await userEvent.click(screen.getByRole('button', { name: 'Boeking opnieuw indienen' }))
    await waitFor(() => expect(onOpnieuw).toHaveBeenCalledTimes(1))
    expect(aanroepen.some((a) => a.startsWith('POST') && a.endsWith('/administraties/adm-1/documenten/doc-1/boek-wachtrij/opnieuw-indienen'))).toBe(true)
    expect(onOpnieuw.mock.calls[0][0]).toMatchObject({ soort: 'ok' })
  })

  it('melding bij mislukte trigger noemt de fout en het vangnet (nooit stil)', () => {
    const m = opnieuwIndienenMelding({ document_id: 'd', status: 'wordt_geboekt', sleutel: null, trigger_uitkomst: 'mislukt', trigger_fout: 'PermissionError: 403' })
    expect(m.soort).toBe('warn')
    expect(m.tekst).toContain('PermissionError: 403')
    expect(m.tekst).toContain('vangnet')
  })
})
