// Store-links (blok F): leeg = niets renderen (geen placeholders); per platform alleen de gevulde link.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { heeftStoreLinks, StoreLinks } from './StoreLinks'

describe('StoreLinks', () => {
  it('rendert niets zonder links (null, undefined, lege strings)', () => {
    const { container, rerender } = render(<StoreLinks config={null} />)
    expect(container).toBeEmptyDOMElement()
    rerender(<StoreLinks config={{ store_link_ios: null, store_link_android: '' }} />)
    expect(container).toBeEmptyDOMElement()
    expect(heeftStoreLinks({ store_link_ios: '', store_link_android: null })).toBe(false)
  })

  it('toont alleen het platform mét link; stop- en fallback-copy', () => {
    const { rerender } = render(<StoreLinks config={{ store_link_ios: 'https://apps.apple.com/x', store_link_android: null }} variant="stop" />)
    expect(screen.getByTestId('store-links')).toHaveTextContent('Download eerst de app')
    expect(screen.getByRole('link', { name: /App Store/ })).toHaveAttribute('href', 'https://apps.apple.com/x')
    expect(screen.queryByRole('link', { name: /Google Play/ })).not.toBeInTheDocument()
    rerender(<StoreLinks config={{ store_link_ios: 'https://apps.apple.com/x', store_link_android: 'https://play.google.com/y' }} variant="fallback" />)
    expect(screen.getByTestId('store-links')).toHaveTextContent('App niet geïnstalleerd? Download hem hier')
    expect(screen.getByRole('link', { name: /Google Play/ })).toHaveAttribute('href', 'https://play.google.com/y')
  })
})
