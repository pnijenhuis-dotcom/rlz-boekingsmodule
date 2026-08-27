"""Document verplaatsen naar een andere administratie (addendum kantoor-run 27-08 punt 5, besluit
Peter 27-08 — herstel van een foute toewijzing).

Waarom een DB-functie: het RLS-beleid op `boekhouding.document` (migratie 0004) en op de kind-
tabellen met een eigen `administratie_id` (vraag, vraag_bericht, afwijzing, iban_accordering,
duplicaat_signaal, factuurmatch(_staat), materiaalmatch, document_accordering, accordering_stap,
document_herinnering) kent uitsluitend `administratie_id = current` (document: óf NULL). Een
UPDATE die `administratie_id` van bron naar doel zet faalt daardoor in élke scope: in de bron-
scope weigert `WITH CHECK` de nieuwe waarde, in de doel-scope ziet `USING` de rij niet. Dat is
precies wat RLS moet doen — behalve voor deze ene, bewuste, geauditeerde handeling.

Gekozen vorm: één SECURITY DEFINER-functie (eigenaar = migratierol, dus RLS-vrij binnen de
functie) die uitsluitend deze verhuizing atomair doet en zichzelf hard poort:
  - de aanroeper MOET gescoped zijn op de bron-administratie (`platform.current_administratie_id()
    = p_van`) — de app-laag toetst de scope op bron én doel vóór de aanroep;
  - het document MOET op status `ontvangen` staan — de servicelaag zet de status vóór de verhuizing
    via de statusmachine terug, en die kent géén pad geboekt/ter_accordering → ontvangen. Zo kan
    een geboekt of bij-de-klant-liggend document ook op DB-niveau nooit van administratie wisselen.
Géén generieke BYPASSRLS-grant (migratie 0001: "een expliciete, aparte beslissing") — de bypass
is beperkt tot deze functie en deze tabellen. Vaste `search_path` tegen search-path-kaping.

Schema-only (functie-DDL), geen datawijziging.

Revision ID: 0080
Revises: 0079
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"

_FUNCTIE = """
CREATE FUNCTION boekhouding.verplaats_document(p_document_id uuid, p_van uuid, p_naar uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_status text;
BEGIN
    IF p_van IS NULL OR p_naar IS NULL OR p_van = p_naar THEN
        RAISE EXCEPTION 'verplaats_document: bron en doel moeten twee verschillende administraties zijn';
    END IF;
    IF platform.current_administratie_id() IS DISTINCT FROM p_van THEN
        RAISE EXCEPTION 'verplaats_document: aanroeper is niet gescoped op de bron-administratie';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM platform.administratie WHERE id = p_naar) THEN
        RAISE EXCEPTION 'verplaats_document: onbekende doeladministratie %', p_naar;
    END IF;

    SELECT status::text INTO v_status
    FROM boekhouding.document
    WHERE id = p_document_id AND administratie_id = p_van
    FOR UPDATE;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'verplaats_document: document % niet gevonden in de bron-administratie', p_document_id;
    END IF;
    IF v_status <> 'ontvangen' THEN
        -- De servicelaag zet het document vóór de verhuizing via de statusmachine op ontvangen;
        -- geboekt/ter_accordering hebben dat pad niet en stranden dus ook hier.
        RAISE EXCEPTION 'verplaats_document: document staat op %, verwacht ontvangen', v_status;
    END IF;

    UPDATE boekhouding.document SET administratie_id = p_naar WHERE id = p_document_id;

    -- Kindtabellen mét eigen administratie_id: rijen van dit document volgen mee, zodat ze in de
    -- doel-scope zichtbaar blijven (vragen/afwijzingen = historie + open vragen; signaal-caches
    -- worden ná de her-extractie in het doel opnieuw berekend).
    UPDATE boekhouding.vraag SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.vraag_bericht b SET administratie_id = p_naar
        FROM boekhouding.vraag v
        WHERE b.vraag_id = v.id AND v.document_id = p_document_id AND b.administratie_id = p_van;
    UPDATE boekhouding.afwijzing SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.iban_accordering SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.duplicaat_signaal SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.factuurmatch SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.factuurmatch_staat SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.materiaalmatch SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.accordering_stap s SET administratie_id = p_naar
        FROM boekhouding.document_accordering a
        WHERE s.accordering_id = a.id AND a.document_id = p_document_id AND s.administratie_id = p_van;
    UPDATE boekhouding.document_accordering SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.document_herinnering SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
END
$$
"""


def upgrade() -> None:
    op.execute(_FUNCTIE)
    op.execute("REVOKE ALL ON FUNCTION boekhouding.verplaats_document(uuid, uuid, uuid) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION boekhouding.verplaats_document(uuid, uuid, uuid) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS boekhouding.verplaats_document(uuid, uuid, uuid)")
