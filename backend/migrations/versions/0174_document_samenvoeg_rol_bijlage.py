"""Bijlagen bij de factuur (Peter 02-10 "één mail = één document — alle bijlagen blijven bij de factuur, scheelt heel veel
werk"; BESLISSINGEN "BOEKEN PRETTIG 1 — BIJLAGEN BIJ DE FACTUUR, RUSTIG SCHERM, OVERHEAD AUTOMATISCH (Peter 02-10)").

Een niet-factuur-bijlage uit dezelfde mail (specificatie, huurstaat, werkbon, foto, xlsx/csv) wordt geen eigen
werkvoorraad-rij meer maar hangt aan de factuur: een `document`-rij mét status `samengevoegd`, `samengevoegd_in_id` =
de factuur (bestaand 0098-patroon: nooit verwijderen, terugvindbaar, terugdraaibaar) en de nieuwe kolom
`samenvoeg_rol` = 'bijlage' | 'bijlage_niet_eenduidig' (meerdere facturen in één mail zonder eenduidige treffer op
factuur-/werknummer: de bijlage hangt aan álle facturen mét chip — liever dubbel dan kwijt). NULL = de bestaande
samenvoeg-hulzen van vóór 02-10 (byte-identiek exemplaar / UBL-beeld), ongewijzigd.

Verplaatsen (0080/0132): de SECURITY DEFINER-functie `verplaats_document` verhuist sindsdien óók de bijlage-rijen van
het document mee, en de 0132-policy `document_verplaatsing` dekt die rijen (`samengevoegd_in_id = het te verplaatsen
document AND samenvoeg_rol IS NOT NULL`) binnen de definer-context — anders bleven ze in de bronadministratie achter.
Schema-only (kolom + CHECK + functie-/policy-DDL), geen datawijziging.

Revision ID: 0174
Revises: 0173
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0174"
down_revision: str | None = "0173"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
_DEFINER_CONTEXT = "current_user IS DISTINCT FROM session_user"
_POLICY_0132 = "id = platform.verplaatsing_document_id()"
_POLICY_0174 = (
    "id = platform.verplaatsing_document_id() OR "
    "(samengevoegd_in_id = platform.verplaatsing_document_id() AND samenvoeg_rol IS NOT NULL)"
)

FUNCTIE_0132 = """
CREATE OR REPLACE FUNCTION boekhouding.verplaats_document(p_document_id uuid, p_van uuid, p_naar uuid)
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

    -- 0132: de verplaatsing-policies (<tabel>_verplaatsing) laten binnen deze SECURITY DEFINER-context
    -- uitsluitend de rijen van dít document van administratie wisselen. Transactie-lokaal (is_local),
    -- dus een EXCEPTION rolt de GUC mee terug.
    PERFORM set_config('app.verplaatsing_document_id', p_document_id::text, true);

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

    -- 0132: kindtabellen die ná 0080 zijn toegevoegd (0108/0110) volgen óók mee.
    UPDATE boekhouding.verplichting_match SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.regel_gb_classificatie SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    PERFORM set_config('app.verplaatsing_document_id', '', true);

END
$$"""

FUNCTIE_0174 = """
CREATE OR REPLACE FUNCTION boekhouding.verplaats_document(p_document_id uuid, p_van uuid, p_naar uuid)
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

    -- 0132: de verplaatsing-policies (<tabel>_verplaatsing) laten binnen deze SECURITY DEFINER-context
    -- uitsluitend de rijen van dít document van administratie wisselen. Transactie-lokaal (is_local),
    -- dus een EXCEPTION rolt de GUC mee terug.
    PERFORM set_config('app.verplaatsing_document_id', p_document_id::text, true);

    UPDATE boekhouding.document SET administratie_id = p_naar WHERE id = p_document_id;
    -- 0174 (bijlagen bij de factuur, Peter 02-10): de bijlage-rijen van dit document (status samengevoegd mét
    -- samenvoeg_rol) reizen mee — policy document_verplaatsing dekt ze binnen deze definer-context.
    UPDATE boekhouding.document SET administratie_id = p_naar
        WHERE samengevoegd_in_id = p_document_id AND administratie_id = p_van
          AND status = 'samengevoegd' AND samenvoeg_rol IS NOT NULL;

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

    -- 0132: kindtabellen die ná 0080 zijn toegevoegd (0108/0110) volgen óók mee.
    UPDATE boekhouding.verplichting_match SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.regel_gb_classificatie SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    PERFORM set_config('app.verplaatsing_document_id', '', true);

END
$$"""


def _policy_sql(voorwaarde: str) -> str:
    uitdrukking = f"(({voorwaarde})) AND {_DEFINER_CONTEXT}"
    return (
        "CREATE POLICY document_verplaatsing ON boekhouding.document AS PERMISSIVE FOR ALL "
        f"USING ({uitdrukking}) WITH CHECK ({uitdrukking})"
    )


def _zet_functie(tekst: str) -> None:
    op.execute(tekst)
    op.execute("REVOKE ALL ON FUNCTION boekhouding.verplaats_document(uuid, uuid, uuid) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION boekhouding.verplaats_document(uuid, uuid, uuid) TO {APP_ROLE}")


def upgrade() -> None:
    op.add_column("document", sa.Column("samenvoeg_rol", sa.Text(), nullable=True), schema="boekhouding")
    op.create_check_constraint(
        "ck_document_samenvoeg_rol",
        "document",
        "samenvoeg_rol IS NULL OR samenvoeg_rol IN ('bijlage', 'bijlage_niet_eenduidig')",
        schema="boekhouding",
    )
    op.execute("DROP POLICY IF EXISTS document_verplaatsing ON boekhouding.document")
    op.execute(_policy_sql(_POLICY_0174))
    _zet_functie(FUNCTIE_0174)


def downgrade() -> None:
    _zet_functie(FUNCTIE_0132)
    op.execute("DROP POLICY IF EXISTS document_verplaatsing ON boekhouding.document")
    op.execute(_policy_sql(_POLICY_0132))
    op.drop_constraint("ck_document_samenvoeg_rol", "document", schema="boekhouding", type_="check")
    op.drop_column("document", "samenvoeg_rol", schema="boekhouding")
