/** Blok 5 feedbackrun 25-09 (FV-14): de modale "Nieuwe crediteur"-dialoog is vervangen door het niet-modale
 * crediteur-zijpaneel (`CrediteurPaneel`) — de factuur blijft leesbaar en scrollbaar. Dit bestand blijft als dunne
 * laag voor bestaande imports; nieuwe code importeert `CrediteurPaneel` direct. */
export {
  CrediteurPaneel as NieuweCrediteurDialog,
  type NieuweCrediteurResultaat,
  type NieuweCrediteurVelden,
} from './CrediteurPaneel'
