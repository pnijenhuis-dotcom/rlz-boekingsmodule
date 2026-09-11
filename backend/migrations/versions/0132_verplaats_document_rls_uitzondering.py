"""Verplaatsen naar een andere administratie — RLS-uitzondering binnen de SECURITY DEFINER-functie (blok 1 run 11-09 middag).

Bug (productie 11-09 11:55, correlatie-id 2fa4a61b-…, tweemaal 500): `POST …/documenten/{id}/verplaats` (Kempen
Facilities → Universal Verkoop) strandde op `InsufficientPrivilege: new row violates row-level security policy for
table "document"` — in de aanroep van `boekhouding.verplaats_document(uuid, uuid, uuid)` (migratie 0080).

Wortel: 0080 nam aan "SECURITY DEFINER, eigenaar = migratierol, dus RLS-vrij binnen de functie". Dat klopt alleen
voor een superuser of een rol mét BYPASSRLS: álle RLS-tabellen dragen `FORCE ROW LEVEL SECURITY`, waardoor ook de
TABEL-EIGENAAR aan het beleid onderworpen is. Lokaal en in CI migreert `postgres` (echte superuser → bypass, dus
alle tests groen); op Cloud SQL is de eigenaarsrol géén superuser en BYPASSRLS is daar niet toekenbaar. De functie
heeft in productie dus NOOIT gewerkt: `UPDATE boekhouding.document SET administratie_id = p_naar` valt in de
bron-scope op WITH CHECK (`administratie_id IS NULL OR = current`), en de elf kindtabellen mét eigen
`administratie_id NOT NULL` + policy `administratie_id = current` bieden geen NULL-hop.

Verworpen alternatieven (zie BESLISSINGEN "VERPLAATSEN — RLS-UITZONDERING BINNEN DE SECURITY DEFINER-FUNCTIE"):
- `SET row_security = off` in de functie: zonder BYPASSRLS weigert Postgres met "query would be affected by
  row-level security policy" — geen effect;
- BYPASSRLS voor de eigenaarsrol: vereist superuser, onmogelijk op Cloud SQL en bovendien "een expliciete, aparte
  beslissing" (0001) met een generieke bypass als gevolg;
- FORCE weghalen op de twaalf tabellen: breekt de conventie (alles FORCE) en maakt de eigenaar overal RLS-vrij;
- DELETE + INSERT in het doel: verboden ("niets verwijderen"), triggergevoelig en het document-id zou wisselen.

Gekozen: de kleinste, expliciete policy-wijziging.
1. Helper `platform.verplaatsing_document_id()` leest de transactie-lokale GUC `app.verplaatsing_document_id`
   (zelfde patroon als `platform.current_administratie_id()`).
2. Per geraakte tabel (document + elf 0080-kindtabellen + verplichting_match/regel_gb_classificatie, die ná 0080
   kwamen en nooit meeverhuisden) één extra PERMISSIVE policy `<tabel>_verplaatsing` FOR ALL:
   `<document-kolom> = platform.verplaatsing_document_id() AND current_user IS DISTINCT FROM session_user`.
   De tweede voorwaarde maakt de uitzondering uitsluitend actief BINNEN een SECURITY DEFINER-context (current_user
   = functie-eigenaar ≠ session_user = `boekhouding_app`). De app-rol kan `current_user` niet wisselen (nergens lid
   van); zet ze zélf de GUC, dan blijft de policy dood — bewezen in tests/security/test_verplaats_rls.py.
   `vraag_bericht` en `accordering_stap` hebben geen document_id: zij toetsen via EXISTS op resp. `vraag` en
   `document_accordering`. Die sub-select loopt zélf óók door RLS; binnen de definer-context geldt dáár dezelfde
   verplaatsing-policy, dus de keten sluit ongeacht de volgorde van de UPDATEs.
3. `boekhouding.verplaats_document` herschreven: identieke poorten als 0080 (bron-scope, status ontvangen, doel
   bestaat), de twee extra kindtabellen mee, plus `set_config('app.verplaatsing_document_id', p_document_id, true)` aan het begin en leegzetten aan
   het eind (een EXCEPTION rolt de transactie én de lokale GUC terug). REVOKE/GRANT EXECUTE ongewijzigd.

`platform.administratie` draagt géén RLS (relrowsecurity = false, geverifieerd 11-09) — de EXISTS-poort op p_naar
werkt voor élke rol, Beheerder of niet. Schema-only (functie- en policy-DDL), geen datawijziging.

Revision ID: 0132
Revises: 0131
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0132"
down_revision: str | None = "0131"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"

#: Alleen binnen een SECURITY DEFINER-functie is current_user (= eigenaar) ≠ session_user (= app-rol).
_DEFINER_CONTEXT = "current_user IS DISTINCT FROM session_user"

#: (tabel, voorwaarde die de rij aan het te verplaatsen document bindt)
POLICIES: tuple[tuple[str, str], ...] = (
    ("document", "id = platform.verplaatsing_document_id()"),
    ("vraag", "document_id = platform.verplaatsing_document_id()"),
    (
        "vraag_bericht",
        "EXISTS (SELECT 1 FROM boekhouding.vraag v "
        "WHERE v.id = vraag_bericht.vraag_id AND v.document_id = platform.verplaatsing_document_id())",
    ),
    ("afwijzing", "document_id = platform.verplaatsing_document_id()"),
    ("iban_accordering", "document_id = platform.verplaatsing_document_id()"),
    ("duplicaat_signaal", "document_id = platform.verplaatsing_document_id()"),
    ("factuurmatch", "document_id = platform.verplaatsing_document_id()"),
    ("factuurmatch_staat", "document_id = platform.verplaatsing_document_id()"),
    ("materiaalmatch", "document_id = platform.verplaatsing_document_id()"),
    (
        "accordering_stap",
        "EXISTS (SELECT 1 FROM boekhouding.document_accordering a "
        "WHERE a.id = accordering_stap.accordering_id AND a.document_id = platform.verplaatsing_document_id())",
    ),
    ("document_accordering", "document_id = platform.verplaatsing_document_id()"),
    ("document_herinnering", "document_id = platform.verplaatsing_document_id()"),
    # Ná 0080 toegevoegde kindtabellen mét eigen administratie_id die 0080 niet kende (gat gevonden 11-09 via de
    # productie-gelijke eigenaar-test): verplichting_match (0110, PK = document_id — de her-extractie in het doel
    # botste op de bron-rij die ze onder RLS niet zag) en regel_gb_classificatie (0108, per-document-cache).
    ("verplichting_match", "document_id = platform.verplaatsing_document_id()"),
    ("regel_gb_classificatie", "document_id = platform.verplaatsing_document_id()"),
)

_HELPER = """
CREATE FUNCTION platform.verplaatsing_document_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('app.verplaatsing_document_id', true), '')::uuid
$$
"""

_KERN_0080 = """
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
{VERPLAATSING_AAN}
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
{VERPLAATSING_UIT}
END
"""

_VERPLAATSING_AAN = """
    -- 0132: de verplaatsing-policies (<tabel>_verplaatsing) laten binnen deze SECURITY DEFINER-context
    -- uitsluitend de rijen van dít document van administratie wisselen. Transactie-lokaal (is_local),
    -- dus een EXCEPTION rolt de GUC mee terug.
    PERFORM set_config('app.verplaatsing_document_id', p_document_id::text, true);
"""
_VERPLAATSING_UIT = """
    -- 0132: kindtabellen die ná 0080 zijn toegevoegd (0108/0110) volgen óók mee.
    UPDATE boekhouding.verplichting_match SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.regel_gb_classificatie SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    PERFORM set_config('app.verplaatsing_document_id', '', true);
"""

_KOP = """
CREATE OR REPLACE FUNCTION boekhouding.verplaats_document(p_document_id uuid, p_van uuid, p_naar uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$"""


def functie_tekst(*, met_verplaatsing_guc: bool) -> str:
    """De functietekst; `met_verplaatsing_guc=False` = de letterlijke 0080-kern (downgrade én de
    regressie-vangst in tests/security/test_verplaats_rls.py gebruiken 'm)."""
    kern = _KERN_0080.replace("{VERPLAATSING_AAN}", _VERPLAATSING_AAN if met_verplaatsing_guc else "").replace(
        "{VERPLAATSING_UIT}", _VERPLAATSING_UIT if met_verplaatsing_guc else ""
    )
    return _KOP + kern + "$$"


def _policy_sql(tabel: str, voorwaarde: str) -> str:
    uitdrukking = f"({voorwaarde}) AND {_DEFINER_CONTEXT}"
    return (
        f"CREATE POLICY {tabel}_verplaatsing ON boekhouding.{tabel} AS PERMISSIVE FOR ALL "
        f"USING ({uitdrukking}) WITH CHECK ({uitdrukking})"
    )


def upgrade() -> None:
    op.execute(_HELPER)
    # Policies worden geëvalueerd als current_user: de app-rol buiten de functie (policy dood, maar de helper
    # moet wél aanroepbaar zijn) en de eigenaar erbinnen.
    op.execute(f"GRANT EXECUTE ON FUNCTION platform.verplaatsing_document_id() TO {APP_ROLE}")
    for tabel, voorwaarde in POLICIES:
        op.execute(_policy_sql(tabel, voorwaarde))
    op.execute(functie_tekst(met_verplaatsing_guc=True))
    op.execute("REVOKE ALL ON FUNCTION boekhouding.verplaats_document(uuid, uuid, uuid) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION boekhouding.verplaats_document(uuid, uuid, uuid) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(functie_tekst(met_verplaatsing_guc=False))
    op.execute("REVOKE ALL ON FUNCTION boekhouding.verplaats_document(uuid, uuid, uuid) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION boekhouding.verplaats_document(uuid, uuid, uuid) TO {APP_ROLE}")
    for tabel, _ in POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {tabel}_verplaatsing ON boekhouding.{tabel}")
    op.execute("DROP FUNCTION IF EXISTS platform.verplaatsing_document_id()")
