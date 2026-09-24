-- naam: grootboek-taal
-- versie: 1
-- doel: Per administratie het aantal actuele grootboekrekeningen waarvan de naam een Engels sleutelwoord draagt (Receivable, Payable, Expenses, Revenue, Bank, Cash, Equity, Tax, Income, Cost) plus voorbeelden en het jongste sync-moment — meetlat Odoo taal-poort nl_NL (bundelrun 24-09 blok 2, Bonte Hoeve)
-- scope: administratie
-- parameters: administratie_id
-- kolommen: totaal, engels, voorbeelden, laatst_gesynchroniseerd
SELECT count(*) AS totaal,
       count(*) FILTER (WHERE g.naam ~* '(receivable|payable|expenses|revenue|\mbank\M|\mcash\M|equity|\mtax\M|income|\mcost)') AS engels,
       left(string_agg(g.code || ' ' || g.naam, ' ~ ' ORDER BY g.code)
            FILTER (WHERE g.naam ~* '(receivable|payable|expenses|revenue|\mbank\M|\mcash\M|equity|\mtax\M|income|\mcost)'), 300) AS voorbeelden,
       max(g.laatst_gesynchroniseerd) AS laatst_gesynchroniseerd
  FROM platform.grootboekrekening g
 WHERE g.administratie_id = CAST(:administratie_id AS uuid)
   AND g.verdwenen_uit_bron_op IS NULL
