// Service worker van de accordeur-PWA — UITSLUITEND voor Web Push (scope /accordeur).
//
// Bewust GEEN fetch-handler en dus geen enkele vorm van caching: de SW-les van 2026-07-13
// (een achtergebleven SW kaapt requests op een gedeelde dev-origin) blijft geldig — deze
// worker raakt het netwerkpad niet aan, dus installatie-/updatepad van de PWA verandert niet.
// De guard in src/main.tsx ruimt alle registraties BUITEN /accordeur nog steeds op.
// skipWaiting + clients.claim: een nieuwe versie neemt direct over (er is geen cache of
// in-flight-gedrag om op te wachten), zodat een verouderde worker nooit blijft hangen.

self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener('push', (event) => {
  // Payload komt uit backend/app/berichten (dataminimalisatie: aantal + deep-link, nooit
  // factuurdetails op het lockscreen). Kapotte/lege payload → generieke melding, nooit stil.
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch {
    data = {}
  }
  const titel = data.titel || 'RLZ Goedkeuren'
  const tekst = data.tekst || 'Er wacht iets op je akkoord.'
  const url = typeof data.url === 'string' && data.url.startsWith('/accordeur') ? data.url : '/accordeur'
  event.waitUntil(
    self.registration.showNotification(titel, {
      body: tekst,
      icon: '/icons/accordeur-192.png',
      badge: '/icons/accordeur-192.png',
      data: { url },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  // Deep-link naar de PWA — de auth-cadans (passkey bij opening) blijft de poort; de melding
  // scheelt alleen navigatie. Bestaand open venster hergebruiken waar het kan.
  event.notification.close()
  const url = (event.notification.data && event.notification.data.url) || '/accordeur'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((vensters) => {
      for (const venster of vensters) {
        if (new URL(venster.url).pathname.startsWith('/accordeur') && 'focus' in venster) {
          if ('navigate' in venster) venster.navigate(url)
          return venster.focus()
        }
      }
      return self.clients.openWindow(url)
    }),
  )
})
