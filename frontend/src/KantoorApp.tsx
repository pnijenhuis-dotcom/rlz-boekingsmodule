// Kantoor-web-app (alles behalve /accordeur) — een eigen lazy chunk zodat de accordeur-PWA
// géén kantoor-bundels laadt (performance-budget accordeur-PWA, BESLISSINGEN punt 4).

import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes, useSearchParams } from 'react-router-dom'
import { initThema } from './ui/thema'
import { ActivateScreen } from './auth/ActivateScreen'
import { useAuth } from './auth/AuthContext'
import { isKantoorRol } from './auth/rollen'
import { landingsPad, useMijnToegang } from './auth/useMijnToegang'
import { useAdministraties } from './werkvoorraad/useAdministraties'
import { LoginScreen } from './auth/LoginScreen'
import { BankDetailScreen } from './bank/BankDetailScreen'
import { DocumentDetailScreen } from './document/DocumentDetailScreen'
import { GebruikersScreen } from './gebruikers/GebruikersScreen'
import { InstellingenScreen } from './instellingen/InstellingenScreen'
import { MeerwerkScreen } from './meerwerk/MeerwerkScreen'
import { OmzetReviewScreen } from './omzet/OmzetReviewScreen'
import { PlanningScreen } from './planning/PlanningScreen'
import { Shell } from './shell/Shell'
import { VerkoopReviewScreen } from './verkoop/VerkoopReviewScreen'
import { WaarborgReviewScreen } from './waarborg/WaarborgReviewScreen'
import { WerkvoorraadScreen } from './werkvoorraad/WerkvoorraadScreen'
import { ArchiefScreen } from './zoeken/ArchiefScreen'
import { ZoekenScreen } from './zoeken/ZoekenScreen'
import { SkeletonPaneel } from './ui/basis'

// Kempen-doorbelasting (blok 3): lazy — het reviewscherm is alleen relevant voor de enkele
// administratie mét doorbelasting; de rest van het kantoor laadt deze chunk nooit.
const DoorbelastingReviewScreen = lazy(() =>
  import('./doorbelasting/DoorbelastingReviewScreen').then((m) => ({ default: m.DoorbelastingReviewScreen })),
)

// Projectenmodule (mockup projecten-invoer.html, 22-08): lazy — steigerbouw-specifiek, alleen
// relevant voor administraties met de uren-&-meerwerk-tak.
const ProjectenScreen = lazy(() => import('./projecten/ProjectenScreen').then((m) => ({ default: m.ProjectenScreen })))
const VoorraadScreen = lazy(() => import('./voorraad/VoorraadScreen').then((m) => ({ default: m.VoorraadScreen })))
const TerugkerendScreen = lazy(() => import('./terugkerend/TerugkerendScreen').then((m) => ({ default: m.TerugkerendScreen })))
// Verplichtingen (blok B 04-09): kantoorbreed overzicht + reviewscherm — lazy, want alleen
// relevant voor administraties die offertes/opdrachtbevestigingen laten accorderen.
const VerplichtingenScreen = lazy(() =>
  import('./verplichting/VerplichtingenScreen').then((m) => ({ default: m.VerplichtingenScreen })),
)
const VerplichtingReviewScreen = lazy(() =>
  import('./verplichting/VerplichtingReviewScreen').then((m) => ({ default: m.VerplichtingReviewScreen })),
)
// Crediteuren-dubbelen v2 (03-09): kantoorbreed mét actie — vervangt het per-administratie-scherm.
const CrediteurenDubbelenScreen = lazy(() =>
  import('./crediteuren/CrediteurenDubbelenScreen').then((m) => ({ default: m.CrediteurenDubbelenScreen })),
)
const ProjectDetailScreenLazy = lazy(() =>
  import('./projecten/ProjectDetailScreen').then((m) => ({ default: m.ProjectDetailScreen })),
)
const ProjectResultaatScreen = lazy(() =>
  import('./projecten/ProjectResultaatScreen').then((m) => ({ default: m.ProjectResultaatScreen })),
)
const ProjectenOverzichtScreen = lazy(() =>
  import('./projecten/ProjectenOverzichtScreen').then((m) => ({ default: m.ProjectenOverzichtScreen })),
)

/** Oude /vragen-links (mail, favorieten, interne verwijzingen) landen op het vragen-deelscherm
 * van de klantpagina; zonder administratie op de kantoorbrede vragen-dwarsdoorsnede.
 * (export voor de redirect-test — niets 404't, IA-besluit 15-08). */
export function VragenRedirect() {
  const [searchParams] = useSearchParams()
  const administratie = searchParams.get('administratie')
  if (!administratie) return <Navigate to="/?filter=vragen" replace />
  const document = searchParams.get('document')
  return (
    <Navigate
      to={`/?administratie=${administratie}&sectie=vragen${document ? `&document=${document}` : ''}`}
      replace
    />
  )
}

/** Slimme landing (C1, besluit Peter 24-08): een medewerker met scope op precies één
 * administratie landt op die klantpagina; mét het module-recht "Meerwerk & urenstaten" en de
 * opt-in op die administratie direct op het steigerbouw-deel. Alleen op de kale root (geen
 * query) en fail-closed: bij twijfel/fout gewoon de werkvoorraad. (export voor de test) */
export function SlimmeLanding() {
  const [searchParams] = useSearchParams()
  const toegang = useMijnToegang()
  const { administraties, fout } = useAdministraties()
  if (searchParams.toString() !== '') return <WerkvoorraadScreen />
  if (toegang === undefined || (administraties === null && !fout)) {
    return (
      <div style={{ padding: 24 }}><SkeletonPaneel /></div>
    )
  }
  const pad = landingsPad(toegang, administraties)
  if (pad) return <Navigate to={pad} replace />
  return <WerkvoorraadScreen />
}

function BeschermdeRoutes() {
  const { status, rol } = useAuth()

  if (status === 'laden') {
    return (
      <div style={{ padding: 24 }}><SkeletonPaneel /></div>
    )
  }
  if (status === 'uitgelogd') {
    return <Navigate to="/login" replace />
  }
  if (!isKantoorRol(rol)) {
    // Fail-closed (rollen-gate-bug kliktest 2026-08-21): de kantoor-shell rendert UITSLUITEND
    // voor een expliciete kantoorrol — accordeur, veldrollen én elke onbekende/nieuwe rol
    // landen in de externe app-surface op /accordeur (waar de rolvertakking ze hun eigen
    // flow geeft). De backend weigert kantoor-endpoints sindsdien óók met 403 op rolniveau;
    // deze redirect is routing, geen beveiliging.
    return <Navigate to="/accordeur" replace />
  }

  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<SlimmeLanding />} />
        {/* IA-verbouwing (designronde 15-08): Vragen en Bank zijn geen eigen tabbladen meer —
            oude URL's redirecten (niets 404't); het rekening-afletterscherm blijft bestaan. */}
        <Route path="/bank" element={<Navigate to="/?filter=bank" replace />} />
        <Route path="/bank/:administratieId" element={<BankDetailScreen />} />
        <Route path="/vragen" element={<VragenRedirect />} />
        <Route path="/zoeken" element={<ZoekenScreen />} />
        <Route
          path="/voorraad"
          element={
            <Suspense fallback={<SkeletonPaneel />}>
              <VoorraadScreen />
            </Suspense>
          }
        />
        <Route
          path="/terugkerend"
          element={
            <Suspense fallback={<SkeletonPaneel />}>
              <TerugkerendScreen />
            </Suspense>
          }
        />
        <Route
          path="/verplichtingen"
          element={
            <Suspense fallback={<SkeletonPaneel />}>
              <VerplichtingenScreen />
            </Suspense>
          }
        />
        <Route
          path="/verplichting/:administratieId/:documentId"
          element={
            <Suspense fallback={<SkeletonPaneel />}>
              <VerplichtingReviewScreen />
            </Suspense>
          }
        />
        <Route path="/archief" element={<ArchiefScreen />} />
        <Route path="/documenten/:administratieId/:documentId" element={<DocumentDetailScreen />} />
        <Route path="/omzet/:administratieId/:documentId" element={<OmzetReviewScreen />} />
        <Route path="/verkoop/:administratieId/:documentId" element={<VerkoopReviewScreen />} />
        <Route path="/waarborg/:administratieId/:documentId" element={<WaarborgReviewScreen />} />
        <Route
          path="/doorbelasting/:administratieId/:documentId"
          element={
            <Suspense fallback={<SkeletonPaneel />}>
              <DoorbelastingReviewScreen />
            </Suspense>
          }
        />
        <Route path="/meerwerk" element={<MeerwerkScreen />} />
        <Route path="/planning" element={<PlanningScreen />} />
        <Route
          path="/projecten"
          element={
            <Suspense fallback={<SkeletonPaneel />}>
              <ProjectenScreen />
            </Suspense>
          }
        />
        <Route
          path="/projecten-resultaat"
          element={
            <Suspense fallback={<SkeletonPaneel />}>
              <ProjectenOverzichtScreen />
            </Suspense>
          }
        />
        <Route
          path="/projecten/:administratieId/:projectId"
          element={
            <Suspense fallback={<SkeletonPaneel />}>
              <ProjectDetailScreenLazy />
            </Suspense>
          }
        />
        <Route
          path="/projecten/:administratieId/:projectId/resultaat"
          element={
            <Suspense fallback={<SkeletonPaneel />}>
              <ProjectResultaatScreen />
            </Suspense>
          }
        />
        <Route path="/gebruikers" element={<GebruikersScreen />} />
        {/* Instellingen v3 (01-09): geen landing meer — /instellingen redirect naar het eerste zichtbare
            nav-item van de rol; administratie-detail is een eigen pagina (vervangt de v2-dialoog). */}
        <Route path="/instellingen" element={<InstellingenScreen />} />
        <Route path="/instellingen/administraties/:administratieId" element={<InstellingenScreen />} />
        <Route path="/instellingen/:sectie" element={<InstellingenScreen />} />
        {/* Crediteuren-dubbelen: sinds v3 een INZICHT-scherm (was Instellingen › Crediteuren); sinds 03-09 (v2)
            kantoorbreed mét actie — élke kantoorrol, binnen de eigen scope (backend vereis_kantoorrol). */}
        <Route
          path="/crediteuren"
          element={
            <Suspense fallback={<SkeletonPaneel />}>
              <CrediteurenDubbelenScreen />
            </Suspense>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

// Thema (fase 1 modernisering): keuze wint, anders systeem — op moduleniveau, VÓÓR de eerste
// render: als effect draaide het ná de kinder-renders, waardoor de ThemaKnop een verouderde
// stand las en de topbar even in het verkeerde thema flitste (kliktest 2026-08-16). Geldt zo
// óók voor de login-/activatieroutes buiten de Shell. De accordeur-PWA heeft een eigen,
// losstaand thema en importeert deze module niet.
initThema()

export default function KantoorApp() {
  return (
    <Routes>
      <Route path="/login" element={<LoginScreen />} />
      <Route path="/activeren" element={<ActivateScreen />} />
      <Route path="/*" element={<BeschermdeRoutes />} />
    </Routes>
  )
}
