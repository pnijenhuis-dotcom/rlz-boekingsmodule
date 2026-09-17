-- naam: bankmutatie-feiten
-- versie: 1
-- doel: Bankmutaties uit de eigen cache mét richting, tegenpartij, afletterstand (open_bedrag) en RLZ-koppelingen — op id, IBAN of omschrijving ("bank is leidend")
-- scope: administratie
-- parameters: administratie_id, mutatie_id, iban, omschrijving
-- optioneel: mutatie_id, iban, omschrijving
-- kolommen: mutatie_id, boekdatum, bedrag, richting, open_bedrag, tegenrekening_iban, tegenpartij_naam, omschrijving, rlz_koppelingen, verdwenen_uit_bron_op
SELECT m.id AS mutatie_id,
       m.boekdatum,
       m.bedrag,
       CASE WHEN m.bedrag < 0 THEN 'uitgaand' WHEN m.bedrag > 0 THEN 'inkomend' ELSE 'nul' END AS richting,
       m.open_bedrag,
       m.tegenrekening_iban,
       m.tegenpartij_naam,
       m.omschrijving,
       m.rlz_koppelingen,
       m.verdwenen_uit_bron_op
  FROM boekhouding.bank_mutatie m
 WHERE m.administratie_id = CAST(:administratie_id AS uuid)
   AND (CAST(:mutatie_id AS text) IS NULL OR m.id = CAST(:mutatie_id AS uuid))
   AND (CAST(:iban AS text) IS NULL OR replace(upper(coalesce(m.tegenrekening_iban, '')), ' ', '') = replace(upper(CAST(:iban AS text)), ' ', ''))
   AND (CAST(:omschrijving AS text) IS NULL OR m.omschrijving ILIKE '%' || CAST(:omschrijving AS text) || '%')
 ORDER BY m.boekdatum DESC, m.id
