// AI-kostenmelding — één bron voor de werkvoorraad-banner én het verbruiksblok op Instellingen (BUG Peter 24-09:
// de banner toetste `limiet_bereikt` = het sticky maandfeit en riep de hele maand "geblokkeerd", ook ná de verhoging
// van € 100 → € 150). Regel: "geblokkeerd" staat er uitsluitend op `geblokkeerd` (live verbruik ≥ limiet);
// `limiet_bereikt` blijft een historisch feit ("limiet bereikt op … bij € …; daarna verhoogd naar € …") en, zolang
// er documenten op heraanbieding wachten, de teller met de weg naar de verzamelbak. Puur; getest in aiKostenStand.test.ts.
import type { AiKostenStatusDto } from './instellingenApi'

export type AiKostenStandSoort = 'geblokkeerd' | 'weer_actief' | 'waarschuwing' | 'geen'

export interface AiKostenStand {
  soort: AiKostenStandSoort
  /** Hoofdregel (zonder de knop). */
  tekst: string
  /** Aantal documenten dat op heraanbieding wacht (alleen bij `weer_actief`). */
  wachten: number
}

function moment(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleString('nl-NL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export function bepaalAiKostenStand(status: AiKostenStatusDto): AiKostenStand {
  const bedrag = `${status.maand}: € ${status.verbruik_eur} van € ${status.limiet_eur}`
  if (status.geblokkeerd) {
    return {
      soort: 'geblokkeerd',
      wachten: status.wachten_op_heraanbieding ?? 0,
      tekst:
        `AI-maandlimiet bereikt (${bedrag}) — AI-verwerking is geblokkeerd; nieuwe documenten volgen het handmatige pad ` +
        'en worden automatisch opnieuw aangeboden zodra er budget is. Limiet aanpassen kan op Instellingen.',
    }
  }
  if (status.limiet_bereikt) {
    const wachten = status.wachten_op_heraanbieding ?? 0
    const bereikt = moment(status.limiet_bereikt_op)
    const sinds = moment(status.weer_actief_sinds)
    const bij = status.limiet_bij_bereiken_eur ? ` bij € ${status.limiet_bij_bereiken_eur}` : ''
    const historie = bereikt ? `limiet bereikt op ${bereikt}${bij}; daarna verhoogd naar € ${status.limiet_eur}` : `limiet daarna verhoogd naar € ${status.limiet_eur}`
    const kop = sinds ? `AI-verwerking weer actief sinds ${sinds}` : 'AI-verwerking weer actief'
    const staart =
      wachten > 0
        ? `${wachten} ${wachten === 1 ? 'document wacht' : 'documenten wachten'} op heraanbieding — ze worden automatisch opnieuw verwerkt.`
        : 'niets wacht meer op heraanbieding.'
    return { soort: 'weer_actief', wachten, tekst: `${kop} (${historie}); ${staart}` }
  }
  if (status.waarschuwing_80) {
    return {
      soort: 'waarschuwing',
      wachten: 0,
      tekst: `AI-kosten op ${status.percentage}% van de maandlimiet (${bedrag}) — bij 100% wordt AI-verwerking geblokkeerd.`,
    }
  }
  return { soort: 'geen', wachten: 0, tekst: '' }
}
