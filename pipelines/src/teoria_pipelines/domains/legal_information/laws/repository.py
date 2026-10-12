from __future__ import annotations

from datetime import date
import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.types.json import Jsonb

from teoria_pipelines.domains.legal_information.laws.models import LawCatalog, LawResponse, LawTarget, ParsedLaw
from teoria_pipelines.domains.legal_information.laws.parsing import LawValidationError, PARSER_VERSION


def listing_hash(listing: dict) -> str:
    return hashlib.sha256(json.dumps(listing, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class LawRepository:
    """Data DB law provenance and immutable parsed content snapshots."""
    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("TEORIA_PIPELINE_DATA_DATABASE_URL is required")
        self.database_url = database_url

    def pinned_law_id(self, target_id: str) -> str | None:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute("SELECT law_id FROM legal_information.law WHERE target_id=%s", (target_id,)).fetchone()
        return row[0] if row else None

    def save_raw(self, execution_id: UUID, response: LawResponse) -> str:
        source_hash = hashlib.sha256(response.raw_body).hexdigest()
        # Strict allowlist prevents OC/authentication entering request provenance.
        allowed = {"query", "LID", "nw", "display", "page", "MST", "efYd"}
        if set(response.query) - allowed:
            raise ValueError("law_unsafe_provenance_parameters")
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "INSERT INTO ingestion.law_raw_payloads VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (operation_id,source_record_hash) DO UPDATE SET "
                "last_seen_at=GREATEST(law_raw_payloads.last_seen_at,EXCLUDED.last_seen_at)",
                (response.operation_id, source_hash, response.content_type, response.raw_body,
                 response.fetched_at, response.fetched_at))
            connection.execute(
                "INSERT INTO ingestion.law_raw_observations VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (execution_id, response.operation_id, source_hash, listing_hash(response.query),
                 Jsonb(response.query), response.fetched_at))
        return source_hash

    def register_catalog(self, target: LawTarget, catalog: LawCatalog) -> None:
        if not catalog.versions or any(v.law_id != catalog.law_id for v in catalog.versions):
            raise LawValidationError("law_incomplete_catalog")
        with psycopg.connect(self.database_url) as connection:
            connection.execute("INSERT INTO legal_information.law(law_id,target_id,target_name) "
                               "VALUES (%s,%s,%s) ON CONFLICT (law_id) DO NOTHING",
                               (catalog.law_id, target.id, target.name))
            pinned = connection.execute("SELECT law_id FROM legal_information.law WHERE target_id=%s FOR UPDATE",
                                        (target.id,)).fetchone()
            if not pinned or pinned[0] != catalog.law_id:
                raise LawValidationError("law_target_identity_changed")
            existing_keys = {(mst, effective) for mst, effective in connection.execute(
                "SELECT mst,effective_date FROM legal_information.law_version WHERE law_id=%s",
                (catalog.law_id,))}
            received_keys = {(v.mst, v.effective_date) for v in catalog.versions}
            if existing_keys - received_keys:
                # A smaller but internally consistent API page set can still
                # have lost history. Retain it and require explicit investigation.
                raise LawValidationError("law_catalog_versions_missing")
            for version in catalog.versions:
                connection.execute(
                    "INSERT INTO legal_information.law_version "
                    "(law_id,mst,effective_date,name,promulgation_date,promulgation_number,amendment_type,listing,listing_hash) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (law_id,mst,effective_date) DO UPDATE SET "
                    "name=EXCLUDED.name,promulgation_date=EXCLUDED.promulgation_date,"
                    "promulgation_number=EXCLUDED.promulgation_number,amendment_type=EXCLUDED.amendment_type,"
                    "listing=EXCLUDED.listing,listing_hash=EXCLUDED.listing_hash",
                    (*version.key, version.name, version.promulgation_date, version.promulgation_number,
                     version.amendment_type, Jsonb(version.listing), listing_hash(version.listing)))
            connection.execute("UPDATE legal_information.law SET last_catalog_at=now(), catalog_version_count=%s "
                               "WHERE law_id=%s", (len(catalog.versions), catalog.law_id))

    def select_versions(self, catalog: LawCatalog, *, reconcile_all: bool, today: date):
        with psycopg.connect(self.database_url) as connection:
            existing = {(mst, effective): (parser, listing) for mst, effective, parser, listing in connection.execute(
                "SELECT v.mst,v.effective_date,s.parser_version,s.listing FROM legal_information.law_version v "
                "JOIN legal_information.law_snapshot s ON s.snapshot_id=v.latest_snapshot_id WHERE v.law_id=%s",
                (catalog.law_id,))}
        selected = []
        for v in catalog.versions:
            previous = existing.get((v.mst, v.effective_date))
            # Use provider status, not a guessed last effective date, for refresh.
            # Keep future slices and new historical rows even on incremental runs.
            refresh = v.listing.get("현행연혁코드") in {"현행", "시행예정"} or v.effective_date > today
            def content_listing(values):
                return {k: value for k, value in values.items()
                        if k not in {"현행연혁코드", "법령상세링크"}}
            changed = previous is not None and (
                previous[0] != PARSER_VERSION or content_listing(previous[1]) != content_listing(v.listing))
            if reconcile_all or refresh or previous is None or changed:
                selected.append(v)
        return selected

    def stored_versions(self, target_id: str | None = None):
        with psycopg.connect(self.database_url, row_factory=psycopg.rows.dict_row) as connection:
            query = ("SELECT l.target_id,v.law_id,v.mst,v.name,v.effective_date,v.promulgation_date,"
                     "v.promulgation_number,v.amendment_type,v.listing,s.snapshot_id,s.parser_version,"
                     "s.source_record_hash,s.last_seen_at FROM legal_information.law_version v "
                     "JOIN legal_information.law l USING(law_id) LEFT JOIN legal_information.law_snapshot s "
                     "ON s.snapshot_id=v.latest_snapshot_id")
            params = []
            if target_id:
                query += " WHERE l.target_id=%s"
                params.append(target_id)
            return connection.execute(query + " ORDER BY v.effective_date DESC,v.mst DESC", params).fetchall()

    def archived_response(self, row: dict) -> LawResponse:
        with psycopg.connect(self.database_url) as connection:
            payload = connection.execute("SELECT payload,content_type FROM ingestion.law_raw_payloads "
                "WHERE operation_id='get_law_version' AND source_record_hash=%s",
                (row["source_record_hash"],)).fetchone()
        if payload is None:
            raise LawValidationError("law_original_response_unavailable")
        return LawResponse("get_law_version", {"MST": row["mst"],
            "efYd": row["effective_date"].strftime("%Y%m%d")}, row["last_seen_at"], payload[1], bytes(payload[0]))

    def save_snapshot(self, parsed: ParsedLaw, response: LawResponse, source_hash: str) -> UUID:
        actual_hash = hashlib.sha256(response.raw_body).hexdigest()
        if actual_hash != source_hash or response.operation_id != "get_law_version":
            raise LawValidationError("law_snapshot_raw_mismatch")
        v = parsed.version
        expected_query = {"MST": v.mst, "efYd": v.effective_date.strftime("%Y%m%d")}
        if response.query != expected_query:
            raise LawValidationError("law_snapshot_request_mismatch")
        snapshot_id = uuid5(NAMESPACE_URL, f"teoria:law:{v.law_id}:{v.mst}:{v.effective_date}:{source_hash}:{parsed.parser_version}")
        with psycopg.connect(self.database_url) as connection:
            # Lock this version so concurrent refreshes cannot change its pointer
            # while a snapshot is being populated.
            connection.execute("SELECT 1 FROM legal_information.law_version WHERE law_id=%s AND mst=%s "
                               "AND effective_date=%s FOR UPDATE", v.key)
            inserted = connection.execute(
                "INSERT INTO legal_information.law_snapshot "
                "(snapshot_id,law_id,mst,effective_date,source_record_hash,parser_version,source_metadata,listing,first_seen_at,last_seen_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING snapshot_id",
                (snapshot_id,*v.key,source_hash,parsed.parser_version,Jsonb(parsed.metadata),Jsonb(v.listing),
                 response.fetched_at,response.fetched_at)).fetchone()
            if inserted:
                for p in parsed.provisions:
                    connection.execute("INSERT INTO legal_information.law_provision "
                        "(snapshot_id,path,parent_path,kind,number,title,content,effective_date,source_xml) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (snapshot_id,p['path'],p['parent_path'],p['kind'],p['number'],p['title'],p['content'],p['effective_date'],p['source_xml']))
                for a in parsed.attachments:
                    connection.execute("INSERT INTO legal_information.law_attachment VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (snapshot_id,a['path'],a['number'],a['branch'],a['kind'],a['title'],a['source_xml']))
            connection.execute("UPDATE legal_information.law_snapshot SET last_seen_at=GREATEST(last_seen_at,%s) "
                               "WHERE snapshot_id=%s", (response.fetched_at,snapshot_id))
            connection.execute(
                "UPDATE legal_information.law_version v SET latest_snapshot_id=%s WHERE law_id=%s AND mst=%s "
                "AND effective_date=%s AND (latest_snapshot_id IS NULL OR "
                "(SELECT last_seen_at FROM legal_information.law_snapshot WHERE snapshot_id=v.latest_snapshot_id)<=%s)",
                (snapshot_id,*v.key,response.fetched_at))
        return snapshot_id

    def start_run(self, execution_id: UUID, reconcile_all: bool, target_count: int):
        with psycopg.connect(self.database_url) as connection:
            connection.execute("INSERT INTO legal_information.law_collection_run "
                "(execution_id,reconcile_all,target_count) VALUES (%s,%s,%s)",
                (execution_id,reconcile_all,target_count))

    def record_progress(self, execution_id: UUID, catalog_count: int, collected: int,
                        provisions: int, failed_targets: list[dict]):
        with psycopg.connect(self.database_url) as connection:
            connection.execute("UPDATE legal_information.law_collection_run SET catalog_version_count=%s, "
                "collected_version_count=%s, provision_count=%s, failed_targets=%s WHERE execution_id=%s",
                (catalog_count,collected,provisions,Jsonb(failed_targets),execution_id))

    def get_provisions(self, law_id: str, mst: str, effective_date: date, article: str | None = None):
        with psycopg.connect(self.database_url, row_factory=psycopg.rows.dict_row) as connection:
            query = ("SELECT v.law_id,v.mst,v.effective_date,s.snapshot_id,s.source_record_hash,s.parser_version,"
                     "p.path,p.parent_path,p.kind,p.number,p.title,p.content,p.effective_date AS provision_effective_date "
                     "FROM legal_information.law_version v JOIN legal_information.law_snapshot s "
                     "ON s.snapshot_id=v.latest_snapshot_id JOIN legal_information.law_provision p USING(snapshot_id) "
                     "WHERE v.law_id=%s AND v.mst=%s AND v.effective_date=%s")
            params = [law_id, mst, effective_date]
            if article:
                query += (" AND (p.path IN (SELECT path FROM legal_information.law_provision "
                          "WHERE snapshot_id=s.snapshot_id AND kind='article' AND number=%s) OR p.path LIKE "
                          "(SELECT path || '/%%' FROM legal_information.law_provision WHERE snapshot_id=s.snapshot_id "
                          "AND kind='article' AND number=%s LIMIT 1))")
                params += [article, article]
            # Numeric XML sibling positions preserve source order: [2] precedes
            # [10], and a parent precedes its descendants. Addenda follow articles.
            order = (" ORDER BY CASE WHEN p.kind='addendum' THEN 1 ELSE 0 END, "
                     r"ARRAY(SELECT (m[1])::integer FROM regexp_matches(p.path,'\[(\d+)\]','g') m)")
            return connection.execute(query + order, params).fetchall()
