// Knop "Opnieuw verwerken (N)" (BUG Peter 24-09): N uit de rijen `ai_limiet_bereikt`; 202 → poll → uitkomstlijst per rij
// (bulk-upload-patroon); 409 (poort dicht) = rode reden, nooit stil.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AiHeraanbiedenKnop, telAiLimietRijen } from './AiHeraanbiedenKnop'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => vi.unstubAllGlobals())

describe('AiHeraanbiedenKnop', () => {
  it('telt alleen rijen met reden ai_limiet_bereikt', () => {
    expect(telAiLimietRijen([{ reden: 'ai_limiet_bereikt' }, { reden: 'tenaamstelling_niet_eenduidig' }, { reden: null }, {}])).toBe(1)
    expect(telAiLimietRijen(null)).toBe(0)
  })

  it('202 → pollt de stand → toont de uitkomst per rij en meldt klaar', async () => {
    const gestart = Date.now()
    let polls = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/verzamelbak/ai-heraanbieden') && init?.method === 'POST') {
          return Promise.resolve(jsonResponse({ voertuig: 'cloud_run_job', kandidaten_verzamelbak: 3, kandidaten_documenten: 1 }, 202))
        }
        if (url.endsWith('/verzamelbak/ai-heraanbieden/stand')) {
          polls += 1
          if (polls < 2) {
            return Promise.resolve(jsonResponse({ bezig: true, geblokkeerd: false, kandidaten_verzamelbak: 3, wachten: 3, laatste_run: null }))
          }
          return Promise.resolve(
            jsonResponse({
              bezig: false,
              geblokkeerd: false,
              kandidaten_verzamelbak: 1,
              wachten: 1,
              laatste_run: {
                run_id: 'r1',
                bron: 'intake_job:facturen',
                status: 'klaar',
                gestart_op: new Date(gestart).toISOString(),
                klaar_op: new Date(gestart + 5000).toISOString(),
                geblokkeerd: false,
                kandidaten: 4,
                kandidaten_verzamelbak: 3,
                kandidaten_documenten: 1,
                gedaan: 3,
                rest: 1,
                tellers: { toegewezen: 2, dubbel: 1, wacht_op_budget: 1 },
                overgeslagen: { kostengrens: 1 },
                gestopt_reden: 'AI-maandlimiet bereikt tijdens de run bij drie.pdf',
                uitkomsten: [
                  { document_id: 'd1', bestandsnaam: 'een.pdf', soort: 'verzamelbak', uitkomst: 'toegewezen', detail: 'toegewezen op tenaamstelling', administratie_id: 'a' },
                  { document_id: 'd2', bestandsnaam: 'twee.pdf', soort: 'verzamelbak', uitkomst: 'dubbel', detail: 'byte-identiek', administratie_id: 'a' },
                  { document_id: 'd3', bestandsnaam: 'drie.pdf', soort: 'verzamelbak', uitkomst: 'wacht_op_budget', detail: null, administratie_id: null },
                  { document_id: 'd4', bestandsnaam: 'vier.pdf', soort: 'document', uitkomst: 'toegewezen', detail: null, administratie_id: 'a' },
                ],
              },
            }),
          )
        }
        return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
      }),
    )
    const onKlaar = vi.fn()
    render(<AiHeraanbiedenKnop aantal={3} onKlaar={onKlaar} pollMs={5} />)
    expect(screen.getByText(/3 rijen wachten sinds de AI-limiet/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Opnieuw verwerken (3)' }))
    expect(await screen.findByTestId('ai-heraanbieden-melding')).toHaveTextContent(/gestart voor 3 verzamelbak-rijen en 1 document/)
    const uitkomst = await screen.findByTestId('ai-heraanbieden-uitkomst')
    expect(uitkomst).toHaveTextContent(/2 toegewezen/)
    expect(uitkomst).toHaveTextContent(/1 dubbel \(al aanwezig — samengevoegd, geen AI\)/)
    expect(uitkomst).toHaveTextContent(/1 wacht op AI-budget/)
    expect(uitkomst).toHaveTextContent(/1 overgeslagen \(kostengrens\)/)
    expect(uitkomst).toHaveTextContent(/AI-maandlimiet bereikt tijdens de run bij drie.pdf/)
    expect(uitkomst).toHaveTextContent('een.pdf')
    expect(uitkomst).toHaveTextContent('drie.pdf')
    await waitFor(() => expect(onKlaar).toHaveBeenCalledTimes(1))
    expect(screen.queryByTestId('ai-heraanbieden-melding')).not.toBeInTheDocument()
  })

  it('409 (poort dicht): rode reden, geen poll', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === 'POST') {
          return Promise.resolve(jsonResponse({ detail: 'AI-maandlimiet bereikt (€ 150,00 van € 150,00 in 2026-09) — opnieuw verwerken kan pas ná een hogere limiet.' }, 409))
        }
        return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
      }),
    )
    render(<AiHeraanbiedenKnop aantal={202} pollMs={5} />)
    await userEvent.click(screen.getByRole('button', { name: 'Opnieuw verwerken (202)' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/AI-maandlimiet bereikt/)
    expect(screen.getByRole('button', { name: 'Opnieuw verwerken (202)' })).not.toBeDisabled()
  })

  it('zonder wachtende rijen: geen knop', () => {
    const { container } = render(<AiHeraanbiedenKnop aantal={0} />)
    expect(container).toBeEmptyDOMElement()
  })
})
