/** IA-verbouwing (designronde 15-08): de Vragen- en Bank-tabbladen vervallen, maar oude URL's
 * blijven werken — redirects, niets 404't. */
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { VragenRedirect } from '../KantoorApp'

function LocatieProbe() {
  const locatie = useLocation()
  return <div data-testid="locatie">{`${locatie.pathname}${locatie.search}`}</div>
}

function renderMet(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/" element={<LocatieProbe />} />
        <Route path="/vragen" element={<VragenRedirect />} />
        <Route path="/bank" element={<Navigate to="/?filter=bank" replace />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('IA-redirects (oude tabblad-URLs)', () => {
  it('/vragen zonder administratie → kantoorbrede vragen-dwarsdoorsnede', () => {
    renderMet('/vragen')
    expect(screen.getByTestId('locatie')).toHaveTextContent('/?filter=vragen')
  })

  it('/vragen met administratie en document → vragen-deelscherm van de klantpagina', () => {
    renderMet('/vragen?administratie=abc&document=def')
    expect(screen.getByTestId('locatie')).toHaveTextContent('/?administratie=abc&sectie=vragen&document=def')
  })

  it('/bank → kantoorbrede bank-dwarsdoorsnede', () => {
    renderMet('/bank')
    expect(screen.getByTestId('locatie')).toHaveTextContent('/?filter=bank')
  })
})
