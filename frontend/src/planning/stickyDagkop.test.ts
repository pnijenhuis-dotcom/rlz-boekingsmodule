import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/** Sticky dagkop planning (Peter 18-09, screenshot: MA 14-9 … VR 18-9 verdwenen bij verticaal scrollen). Playwright staat
 * niet in de repo (18-09) — deze guard toetst de bron: beide grids (Personeel + Transport) staan in een intern scrollende
 * `.tabel-scroll.sticky-koppen.plan-scroll` en components.css geeft de thead-cellen een dekkende achtergrond + rand. De
 * kliktest (scroll 800 px → kop zichtbaar) staat in het rapport. */

const lees = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8')

describe('sticky dagkop planning', () => {
  it('Personeel-grid en Transport-dagagenda scrollen intern mét sticky koppen', () => {
    for (const bestand of ['./PlanningScreen.tsx', './TransportTab.tsx']) {
      const bron = lees(bestand)
      const wrapper = bron.match(/className="tabel-scroll sticky-koppen plan-scroll"[\s\S]{0,200}?<table className="plan-grid"/)
      expect(wrapper, `${bestand}: plan-grid moet in .tabel-scroll.sticky-koppen.plan-scroll staan`).not.toBeNull()
      expect(bron.match(/<div className="tabel-scroll">\s*<table className="plan-grid"/), `${bestand}: kale wrapper`).toBeNull()
    }
  })
  it('components.css: sticky th (top 0), dekkende achtergrond, onderrand en een max-hoogte voor de scrollcontainer', () => {
    const css = lees('../styles/components.css')
    expect(css).toMatch(/\.tabel-scroll\.sticky-koppen th \{[^}]*position: sticky;[^}]*top: 0;/)
    expect(css).toMatch(/\.plan-scroll \{[^}]*max-height:/)
    const kop = css.match(/\.plan-scroll\.sticky-koppen \.plan-grid thead th \{([^}]*)\}/)
    expect(kop).not.toBeNull()
    expect(kop![1]).toMatch(/background: var\(--panel\)/)
    expect(kop![1]).toMatch(/box-shadow: 0 1px 0/)
  })
})
