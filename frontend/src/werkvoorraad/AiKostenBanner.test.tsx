// Werkvoorraad-banner (BUG Peter 24-09): ná de verhoging géén "geblokkeerd" meer; één regel "weer actief" mét de
// tekstknop naar de verzamelbak; geblokkeerd = rode alert.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { AiKostenStatusDto } from '../instellingen/instellingenApi'
import { AiKostenBannerInhoud, VERZAMELBAK_ANKER } from './AiKostenBanner'

const BASIS: AiKostenStatusDto = {
  maand: '2026-09',
  verbruik_eur: '102.23',
  limiet_eur: '150.00',
  percentage: 68,
  waarschuwing_80: true,
  limiet_bereikt: true,
  geblokkeerd: false,
  limiet_bereikt_op: '2026-09-23T17:05:00Z',
  limiet_bij_bereiken_eur: '100.00',
  weer_actief_sinds: '2026-09-23T19:22:00Z',
  wachten_op_heraanbieding: 202,
}

describe('AiKostenBannerInhoud', () => {
  it('limiet bereikt maar niet geblokkeerd: status-regel zonder "geblokkeerd", knop scrolt naar de verzamelbak', async () => {
    const anker = document.createElement('div')
    anker.id = VERZAMELBAK_ANKER
    anker.scrollIntoView = vi.fn()
    document.body.appendChild(anker)
    render(<AiKostenBannerInhoud status={BASIS} />)
    const banner = screen.getByTestId('ai-kosten-banner')
    expect(banner).toHaveAttribute('role', 'status')
    expect(banner).not.toHaveTextContent(/geblokkeerd/i)
    expect(banner).toHaveTextContent(/weer actief sinds/)
    expect(banner).toHaveTextContent(/202 documenten wachten op heraanbieding/)
    await userEvent.click(screen.getByRole('button', { name: 'Naar de verzamelbak' }))
    expect(anker.scrollIntoView).toHaveBeenCalled()
    anker.remove()
  })

  it('geblokkeerd: rode alert', () => {
    render(<AiKostenBannerInhoud status={{ ...BASIS, geblokkeerd: true, verbruik_eur: '150.10' }} />)
    const banner = screen.getByRole('alert')
    expect(banner).toHaveTextContent(/AI-verwerking is geblokkeerd/)
    expect(screen.queryByRole('button', { name: 'Naar de verzamelbak' })).not.toBeInTheDocument()
  })

  it('niets te melden: geen banner', () => {
    const { container } = render(<AiKostenBannerInhoud status={{ ...BASIS, limiet_bereikt: false, waarschuwing_80: false }} />)
    expect(container).toBeEmptyDOMElement()
  })
})
