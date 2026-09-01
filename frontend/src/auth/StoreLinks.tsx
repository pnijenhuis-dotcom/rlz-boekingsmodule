// Store-links (blok F nachtrun 01/02-09): "Download eerst de app" — alleen zichtbaar zodra een link gevuld is
// (config STORE_LINK_IOS/STORE_LINK_ANDROID via /auth/webauthn/config), per platform alleen als zijn link
// gevuld is. Leeg = niets renderen: exact het huidige gedrag zolang Apple/Google nog niet goedgekeurd hebben.
import type { WebauthnConfigDto } from '../accordeur/webauthnClient'

export type StoreLinkConfig = Pick<WebauthnConfigDto, 'store_link_ios' | 'store_link_android'> | null | undefined

export function heeftStoreLinks(config: StoreLinkConfig): boolean {
  return Boolean(config?.store_link_ios || config?.store_link_android)
}

export function StoreLinks({ config, variant = 'stop' }: { config: StoreLinkConfig; variant?: 'stop' | 'fallback' }) {
  if (!heeftStoreLinks(config)) return null
  return (
    <div className="store-links" data-testid="store-links">
      <b>{variant === 'stop' ? 'Download eerst de app' : 'App niet geïnstalleerd? Download hem hier'}</b>
      <p className="hint" style={{ margin: '4px 0 6px' }}>
        {variant === 'stop'
          ? 'Installeer de app op uw telefoon en open daarna de link uit de e-mail (of scan de QR) — de app neemt de activatie over.'
          : 'Deze link hoort in de app geopend te worden. Installeer de app en open de link uit de e-mail opnieuw; in de browser doorgaan kan ook.'}
      </p>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        {config?.store_link_ios && (
          <a className="btn secondary" href={config.store_link_ios} target="_blank" rel="noreferrer">
            iPhone / iPad — App Store
          </a>
        )}
        {config?.store_link_android && (
          <a className="btn secondary" href={config.store_link_android} target="_blank" rel="noreferrer">
            Android — Google Play
          </a>
        )}
      </div>
    </div>
  )
}
