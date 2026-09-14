uitgevoerd 2026-09-14, rapport: docs/rapporten/2026-09-14-bug-doorbelasting-instellingen.md

BUG (melding Peter 14-09 ~15:00) — Instellingen › Doorbelasting laadt niet in productie

Scherm: frontend/src/doorbelasting/DoorbelastingInstellingen.tsx r.190 "De doorbelasting-instellingen konden niet geladen worden." Backend antwoordde met de centrale 500-handler (app/main.py r.115): "Er ging iets mis bij het verwerken van je aanvraag — code 0f7c36ca-49ba-4524-950b-d674b0ff3a19".

1. Oorzaak vinden, niet raden: lees de productie-log op de correlatie-id met gcloud (deze Mac is als owner ingelogd; alleen lezen):
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="rlz-backend" AND textPayload:"0f7c36ca-49ba-4524-950b-d674b0ff3a19" OR jsonPayload.correlatie_id="0f7c36ca-49ba-4524-950b-d674b0ff3a19"' --project rlz-boekhouding --limit 50 --freshness 6h
   Zoek de traceback + het pad (verwacht: één van de GET-routes die doorbelastingApi.ts aanroept bij laden — whitelist/mapping, doelentiteiten, projecten van de doeladministratie). Noteer route, administratie (geanonimiseerd), exception en regel. Geen productie-data in het rapport behalve de exception-tekst.
2. Reproduceer in een test (unit of API-test met de stand die de fout triggert — waarschijnlijk een dataconditie: gearchiveerde doelentiteit, ontbrekende koppeling, None waar een str verwacht wordt, of een 0140/0135-gevolg). Fix aan de bron; de route mag nooit meer 500 geven op een dataconditie — leesbare lege stand of 409/422 mét tekst, conform "niets verdwijnt stil".
3. Sweep: dezelfde fout-klasse in de zusterroutes van het doorbelasting-scherm (zelfde loader-patroon) meenemen.
4. Af: gouden set + tests groen, tsc -b; commit → deploy loopt automatisch; ná deploy: dezelfde logquery moet voor een nieuwe laadpoging geen 500 meer tonen — Peter test het scherm opnieuw. Rapport docs/rapporten/2026-09-14-bug-doorbelasting-instellingen.md + INDEX (oorzaak in twee zinnen gewone taal bovenaan, voor Peter). Dit bestand naar gedaan/.
