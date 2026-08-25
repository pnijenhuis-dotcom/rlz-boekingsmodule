import { useCallback, useEffect, useState } from 'react'
import { ApiError, apiJson } from '../api/client'
import type { AdministratieDto, VendorLijstDto } from '../api/types'
import {
  haalCatalogus,
  haalLeveranciers,
  haalProducten,
  seedUniversal,
  zetCategorie,
  zetLeverancier,
  zetProduct,
  type CategorieDto,
  type LeverancierDto,
  type ProductDto,
} from '../planning/transportApi'
import { Badge, Button, Checkbox, Paginering, Select, useToastOptioneel } from '../ui/basis'

/* Materiaalcatalogus per leverancier (steigerbouw-run D2, Beheerder): leveranciers (bestel-
 * mailadres, crediteur-koppeling voor de factuurcontrole D6), categorieën + producten met
 * verpakkingseenheid en m²-lengte (Σ aantal × lengte / 4,6 — de formule uit de bestellijst),
 * seed "Standaardcatalogus laden" uit verkenning/voorbeelden/bestellijst-universal-voorbeeld.xlsx
 * (idempotent). Schaalbaar (C4): zoeken + paginering server-side. */
export function MateriaalCatalogusBeheer({ administraties }: { administraties: AdministratieDto[] }) {
  const { meld } = useToastOptioneel()
  const [administratieId, setAdministratieId] = useState(administraties[0]?.id ?? '')
  const [leveranciers, setLeveranciers] = useState<LeverancierDto[] | null>(null)
  const [leverancierId, setLeverancierId] = useState<string | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [zoek, setZoek] = useState('')
  const [pagina, setPagina] = useState(1)
  const [producten, setProducten] = useState<{ items: ProductDto[]; totaal: number } | null>(null)
  const [categorieen, setCategorieen] = useState<CategorieDto[]>([])
  const [bewerkLev, setBewerkLev] = useState<Partial<LeverancierDto> | null>(null)
  const [bewerkProd, setBewerkProd] = useState<Partial<ProductDto> | null>(null)
  const [nieuweCat, setNieuweCat] = useState('')
  const [vendors, setVendors] = useState<{ id: string; naam: string }[]>([])

  const laadLeveranciers = useCallback(() => {
    if (!administratieId) return
    setFout(null)
    haalLeveranciers(administratieId, '', false)
      .then((l) => {
        setLeveranciers(l)
        if (l.length > 0 && !l.some((x) => x.id === leverancierId)) setLeverancierId(l[0].id)
      })
      .catch((err: unknown) => {
        setLeveranciers([])
        setFout(err instanceof ApiError && err.status === 409 ? 'Uren & meerwerk staat uit voor deze administratie — de materiaalcatalogus hoort bij de steigerbouw-tak.' : err instanceof Error ? err.message : 'Laden mislukt')
      })
    apiJson<VendorLijstDto>(`/administraties/${administratieId}/crediteuren`)
      .then((v) => setVendors(v.crediteuren.map((c) => ({ id: c.id, naam: c.naam ?? c.id }))))
      .catch(() => setVendors([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [administratieId])
  useEffect(() => {
    laadLeveranciers()
  }, [laadLeveranciers])

  const laadProducten = useCallback(() => {
    if (!administratieId || !leverancierId) return
    haalProducten(administratieId, { leverancier_id: leverancierId, zoek, pagina, per_pagina: 25 })
      .then((r) => setProducten({ items: r.items, totaal: r.totaal }))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Producten laden mislukt'))
    haalCatalogus(administratieId, leverancierId, false).then(setCategorieen).catch(() => setCategorieen([]))
  }, [administratieId, leverancierId, zoek, pagina])
  useEffect(() => {
    laadProducten()
  }, [laadProducten])

  async function actie(fn: () => Promise<unknown>, tekst: string) {
    setBezig(true)
    setFout(null)
    try {
      await fn()
      meld(tekst)
      laadLeveranciers()
      laadProducten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Actie mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const lev = leveranciers?.find((l) => l.id === leverancierId) ?? null

  return (
    <div className="panel">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>📦 Materiaalcatalogus (transport &amp; bestellingen)</h2>
        <Select value={administratieId} onChange={(e) => { setAdministratieId(e.target.value); setLeverancierId(null); setPagina(1) }} aria-label="Administratie">
          {administraties.map((a) => (
            <option key={a.id} value={a.id}>
              {a.naam}
            </option>
          ))}
        </Select>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <Button variant="secundair" maat="klein" disabled={bezig || !administratieId} onClick={() => void actie(() => seedUniversal(administratieId).then((r) => meld(`${r.producten_nieuw} nieuwe producten, ${r.producten_bestaand} bestonden al.`)), 'Standaardcatalogus Universal geladen (idempotent).')}>
            Standaardcatalogus laden (Universal)
          </Button>
          <Button maat="klein" onClick={() => setBewerkLev({ naam: '', actief: true })}>
            + Leverancier
          </Button>
        </div>
      </div>
      <p className="hint" style={{ marginTop: 6 }}>
        Per leverancier (eigen verhuurbedrijven): bestel-mailadres voor de PDF-bon, koppeling met de RLZ-crediteur voor de factuurcontrole (D6),
        categorieën + producten met verpakkingseenheid en m²-lengte — m² = Σ(aantal × lengte) / 4,6 (formule uit de bestellijst). Producten
        verdwijnen nooit (inactief zetten). Alles geauditeerd.
      </p>
      {fout && <div className="fout">{fout}</div>}
      {leveranciers !== null && leveranciers.length === 0 && !fout && <p className="hint">Nog geen leveranciers — laad de standaardcatalogus of voeg een leverancier toe.</p>}
      {leveranciers !== null && leveranciers.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '10px 0' }}>
          {leveranciers.map((l) => (
            <button key={l.id} className="linkbtn" onClick={() => { setLeverancierId(l.id); setPagina(1) }} style={{ padding: 0 }}>
              <Badge variant={l.id === leverancierId ? 'info' : l.actief ? 'stil' : 'danger'}>
                {l.naam} · {l.aantal_producten}
                {!l.actief ? ' · inactief' : ''}
              </Badge>
            </button>
          ))}
        </div>
      )}
      {lev && (
        <>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', fontSize: 12.5 }}>
            <b>{lev.naam}</b>
            <span className="hint" style={{ margin: 0 }}>{lev.bestel_email ?? '⚠ geen bestel-mailadres'}</span>
            <span className="hint" style={{ margin: 0 }}>{lev.vendor_id ? `crediteur: ${vendors.find((v) => v.id === lev.vendor_id)?.naam ?? lev.vendor_id}` : 'geen crediteur-koppeling (factuurcontrole uit)'}</span>
            <Button variant="ghost" maat="klein" onClick={() => setBewerkLev(lev)}>
              wijzig leverancier
            </Button>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
              <input placeholder="Nieuwe categorie…" value={nieuweCat} onChange={(e) => setNieuweCat(e.target.value)} style={{ width: 180 }} />
              <Button variant="secundair" maat="klein" disabled={nieuweCat.trim().length < 2 || bezig} onClick={() => void actie(() => zetCategorie(administratieId, { leverancier_id: lev.id, naam: nieuweCat.trim(), bundel: 'overig', volgorde: categorieen.length + 1, actief: true }).then(() => setNieuweCat('')), 'Categorie toegevoegd.')}>
                + Categorie
              </Button>
              <Button maat="klein" disabled={categorieen.length === 0} onClick={() => setBewerkProd({ leverancier_id: lev.id, categorie_id: categorieen[0]?.id, naam: '', eenheid: 'stuks', actief: true, volgorde: 0 })}>
                + Product
              </Button>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, margin: '10px 0 6px' }}>
            <input type="search" placeholder="Zoek product of categorie…" value={zoek} onChange={(e) => { setZoek(e.target.value); setPagina(1) }} style={{ flex: '0 1 320px' }} aria-label="Zoek producten" />
            {producten && <span className="hint" style={{ alignSelf: 'center', margin: 0 }}>{producten.totaal} producten</span>}
          </div>
          {producten && (
            <div className="tabel-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Categorie</th>
                    <th>Product</th>
                    <th>Verpakking</th>
                    <th>Eenheid</th>
                    <th className="amount">m²-lengte</th>
                    <th>Actief</th>
                    <th className="acties" />
                  </tr>
                </thead>
                <tbody>
                  {producten.items.map((p) => (
                    <tr key={p.id} style={{ opacity: p.actief ? 1 : 0.55 }}>
                      <td>{p.categorie_naam}</td>
                      <td>{p.naam}</td>
                      <td>{p.verpakking ?? '—'}</td>
                      <td>{p.eenheid}</td>
                      <td className="amount">{p.m2_lengte ? `${Number(p.m2_lengte).toLocaleString('nl-NL')} m` : '—'}</td>
                      <td>{p.actief ? <Badge variant="ok">ja</Badge> : <Badge variant="stil">nee</Badge>}</td>
                      <td className="acties">
                        <Button variant="ghost" maat="klein" onClick={() => setBewerkProd(p)}>
                          wijzig
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {producten && <Paginering pagina={pagina} totaal={producten.totaal} onPagina={setPagina} label="producten" />}
        </>
      )}

      {bewerkLev && (
        <div className="modal-bg" role="presentation" onClick={() => !bezig && setBewerkLev(null)}>
          <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <h2>{bewerkLev.id ? 'Leverancier wijzigen' : 'Nieuwe leverancier'}</h2>
            <label className="hint" style={{ display: 'block' }}>
              Naam
              <input value={bewerkLev.naam ?? ''} onChange={(e) => setBewerkLev({ ...bewerkLev, naam: e.target.value })} style={{ width: '100%' }} />
            </label>
            <label className="hint" style={{ display: 'block', marginTop: 8 }}>
              Bestel-mailadres (ontvanger van de PDF-bon)
              <input type="email" value={bewerkLev.bestel_email ?? ''} onChange={(e) => setBewerkLev({ ...bewerkLev, bestel_email: e.target.value })} style={{ width: '100%' }} />
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 8 }}>
              <label className="hint" style={{ margin: 0 }}>
                Telefoon
                <input value={bewerkLev.telefoon ?? ''} onChange={(e) => setBewerkLev({ ...bewerkLev, telefoon: e.target.value })} style={{ width: '100%' }} />
              </label>
              <label className="hint" style={{ margin: 0 }}>
                Adres
                <input value={bewerkLev.adres ?? ''} onChange={(e) => setBewerkLev({ ...bewerkLev, adres: e.target.value })} style={{ width: '100%' }} />
              </label>
            </div>
            <label className="hint" style={{ display: 'block', marginTop: 8 }}>
              RLZ-crediteur (factuurcontrole materiaal, D6)
              <Select value={bewerkLev.vendor_id ?? ''} onChange={(e) => setBewerkLev({ ...bewerkLev, vendor_id: e.target.value || null })} className="w-full">
                <option value="">— geen koppeling —</option>
                {vendors.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.naam}
                  </option>
                ))}
              </Select>
            </label>
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8, fontSize: 12.5 }}>
              <Checkbox checked={bewerkLev.actief ?? true} onChange={(e) => setBewerkLev({ ...bewerkLev, actief: e.target.checked })} /> actief
            </label>
            <div className="actions">
              <button className="btn secondary" onClick={() => setBewerkLev(null)} disabled={bezig}>
                Annuleren
              </button>
              <button
                className="btn"
                disabled={bezig || !(bewerkLev.naam ?? '').trim()}
                onClick={() =>
                  void actie(
                    () =>
                      zetLeverancier(administratieId, {
                        id: bewerkLev.id,
                        naam: (bewerkLev.naam ?? '').trim(),
                        bestel_email: bewerkLev.bestel_email || null,
                        telefoon: bewerkLev.telefoon || null,
                        adres: bewerkLev.adres || null,
                        vendor_id: bewerkLev.vendor_id || null,
                        actief: bewerkLev.actief ?? true,
                      }).then(() => setBewerkLev(null)),
                    'Leverancier opgeslagen — geauditeerd.',
                  )
                }
              >
                Opslaan
              </button>
            </div>
          </div>
        </div>
      )}

      {bewerkProd && lev && (
        <div className="modal-bg" role="presentation" onClick={() => !bezig && setBewerkProd(null)}>
          <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <h2>{bewerkProd.id ? 'Product wijzigen' : 'Nieuw product'}</h2>
            <label className="hint" style={{ display: 'block' }}>
              Categorie
              <Select value={bewerkProd.categorie_id ?? ''} onChange={(e) => setBewerkProd({ ...bewerkProd, categorie_id: e.target.value })} className="w-full">
                {categorieen.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.naam} ({c.bundel})
                  </option>
                ))}
              </Select>
            </label>
            <label className="hint" style={{ display: 'block', marginTop: 8 }}>
              Productnaam
              <input value={bewerkProd.naam ?? ''} onChange={(e) => setBewerkProd({ ...bewerkProd, naam: e.target.value })} style={{ width: '100%' }} />
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 8 }}>
              <label className="hint" style={{ margin: 0 }}>
                Verpakking (bv. 100 st.)
                <input value={bewerkProd.verpakking ?? ''} onChange={(e) => setBewerkProd({ ...bewerkProd, verpakking: e.target.value })} style={{ width: '100%' }} />
              </label>
              <label className="hint" style={{ margin: 0 }}>
                Eenheid
                <Select value={bewerkProd.eenheid ?? 'stuks'} onChange={(e) => setBewerkProd({ ...bewerkProd, eenheid: e.target.value })} className="w-full">
                  {['stuks', 'rol', 'm1', 'm2', 'set'].map((e) => (
                    <option key={e} value={e}>
                      {e}
                    </option>
                  ))}
                </Select>
              </label>
              <label className="hint" style={{ margin: 0 }}>
                m²-lengte (m, leeg = telt niet)
                <input inputMode="decimal" value={bewerkProd.m2_lengte ?? ''} onChange={(e) => setBewerkProd({ ...bewerkProd, m2_lengte: e.target.value })} style={{ width: '100%' }} />
              </label>
            </div>
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8, fontSize: 12.5 }}>
              <Checkbox checked={bewerkProd.actief ?? true} onChange={(e) => setBewerkProd({ ...bewerkProd, actief: e.target.checked })} /> actief
            </label>
            <div className="actions">
              <button className="btn secondary" onClick={() => setBewerkProd(null)} disabled={bezig}>
                Annuleren
              </button>
              <button
                className="btn"
                disabled={bezig || !(bewerkProd.naam ?? '').trim() || !bewerkProd.categorie_id}
                onClick={() =>
                  void actie(
                    () =>
                      zetProduct(administratieId, {
                        id: bewerkProd.id,
                        leverancier_id: lev.id,
                        categorie_id: bewerkProd.categorie_id!,
                        naam: (bewerkProd.naam ?? '').trim(),
                        verpakking: bewerkProd.verpakking || null,
                        eenheid: bewerkProd.eenheid ?? 'stuks',
                        m2_lengte: bewerkProd.m2_lengte ? String(bewerkProd.m2_lengte).replace(',', '.') : null,
                        volgorde: bewerkProd.volgorde ?? 0,
                        actief: bewerkProd.actief ?? true,
                      }).then(() => setBewerkProd(null)),
                    'Product opgeslagen — geauditeerd.',
                  )
                }
              >
                Opslaan
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
