import { describe, expect, it } from 'vitest'
import { metViewerOpties } from './pdfWeergaveUrl'

describe('metViewerOpties (fix C2 04-09: miniaturen-zijbalk standaard dicht)', () => {
  it('zet de openingsstand op een kale blob-URL', () => {
    expect(metViewerOpties('blob:http://localhost/abc-123')).toBe(
      'blob:http://localhost/abc-123#pagemode=none&navpanes=0&view=FitH',
    )
  })

  it('is idempotent — nooit een dubbele # of dubbele sleutel', () => {
    const eenmaal = metViewerOpties('blob:http://localhost/abc-123')
    expect(metViewerOpties(eenmaal)).toBe(eenmaal)
    expect(metViewerOpties(eenmaal).match(/#/g)).toHaveLength(1)
  })

  it('respecteert een al gezette sleutel en vult alleen de rest aan', () => {
    expect(metViewerOpties('x.pdf#page=3&view=Fit')).toBe('x.pdf#page=3&view=Fit&pagemode=none&navpanes=0')
  })

  it('zet nooit toolbar=0 — de gebruiker moet de zijbalk via ☰ kunnen openen', () => {
    expect(metViewerOpties('x.pdf')).not.toContain('toolbar')
  })

  it('laat een lege waarde ongemoeid', () => {
    expect(metViewerOpties('')).toBe('')
  })
})
