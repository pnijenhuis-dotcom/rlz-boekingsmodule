// "Toon QR" (D3, 01-09): de BESTAANDE link als QR — dezelfde link staat er leesbaar onder; gesloten = niets.
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { QrLinkDialog } from './QrLinkDialog'

describe('QrLinkDialog', () => {
  it('rendert de QR (svg) en de link zelf; link null = geen dialoog', () => {
    const link = 'https://app.test/activeren?token=abc'
    const { rerender } = render(<QrLinkDialog link={link} titel="QR-uitnodiging" onSluiten={vi.fn()} />)
    const dialoog = screen.getByTestId('qr-dialoog')
    expect(dialoog.querySelector('svg')).not.toBeNull()
    expect(dialoog).toHaveTextContent(link)
    expect(dialoog).toHaveTextContent(/dezelfde eenmalige link/)
    rerender(<QrLinkDialog link={null} titel="QR-uitnodiging" onSluiten={vi.fn()} />)
    expect(screen.queryByTestId('qr-dialoog')).not.toBeInTheDocument()
  })
})
