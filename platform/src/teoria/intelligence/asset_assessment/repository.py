from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from teoria.intelligence.repository import SuggestionRepository, _jsonable


class AssessmentRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def create(self, *, target_ref: dict, request, actor: str, model: str) -> dict:
        key = hashlib.sha256(json.dumps({
            'target': target_ref, **request.model_dump(mode='json', exclude={'table_fqn'}),
        }, sort_keys=True).encode()).hexdigest()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute('''
                INSERT INTO intelligence.asset_assessments
                    (assessment_id,target_ref,scopes,column_names,assessment_date,
                     disclosure_context,requested_by,request_key,model_name)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (request_key) WHERE status IN ('queued','running')
                DO UPDATE SET request_key=EXCLUDED.request_key RETURNING assessment_id
            ''', (uuid4(), Jsonb(target_ref), request.scopes, request.column_names,
                  request.assessment_date, request.disclosure_context, actor, key, model)).fetchone()
        return self.get(row['assessment_id'])

    def get(self, identifier: UUID) -> dict:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute('SELECT * FROM intelligence.asset_assessments WHERE assessment_id=%s', (identifier,)).fetchone()
            if row is None:
                raise KeyError(identifier)
            ids = connection.execute('SELECT suggestion_id FROM intelligence.asset_assessment_suggestions WHERE assessment_id=%s ORDER BY suggestion_id', (identifier,)).fetchall()
        result = _jsonable(dict(row))
        for finding in result['findings']:
            if finding.get('scope') != 'disclosure_assessment':
                for key in ('information_type', 'internal_processing', 'disclosure_recommendation',
                            'protection_recommendation', 'tag_candidates'):
                    finding.pop(key, None)
        result.pop('claim_token', None)
        result.pop('request_key', None)
        result['suggestion_ids'] = [str(item['suggestion_id']) for item in ids]
        return result

    def list(self, table_id: UUID, *, limit: int = 10) -> list[dict]:
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute('''SELECT assessment_id FROM intelligence.asset_assessments
                WHERE target_ref->>'entity_id'=%s ORDER BY created_at DESC LIMIT %s''', (str(table_id), limit)).fetchall()
        return [self.get(row[0]) for row in rows]

    def claim(self) -> dict | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute('''UPDATE intelligence.asset_assessments SET status='failed',
                error_code='worker_lease_exhausted',finished_at=now(),claim_token=NULL,lease_until=NULL
                WHERE status='running' AND lease_until<now() AND attempts>=3''')
            row = connection.execute('''WITH next AS (
                SELECT assessment_id FROM intelligence.asset_assessments
                WHERE status='queued' OR (status='running' AND lease_until<now() AND attempts<3)
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
                UPDATE intelligence.asset_assessments a SET status='running',attempts=attempts+1,
                    claim_token=%s,lease_until=now()+interval '10 minutes',started_at=now(),error_code=NULL
                FROM next WHERE a.assessment_id=next.assessment_id RETURNING a.*''', (uuid4(),)).fetchone()
        return dict(row) if row else None

    def finish(self, job: dict, *, proposals: list[dict], findings: list[dict], partial: bool = False, error_code: str | None = None) -> bool:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute('''SELECT assessment_id FROM intelligence.asset_assessments
                WHERE assessment_id=%s AND status='running' AND claim_token=%s AND lease_until>now()
                FOR UPDATE''', (job['assessment_id'], job['claim_token'])).fetchone()
            if row is None:
                return False
            for proposal in sorted(proposals, key=lambda p: (p['target_ref'], p['suggestion_type'])):
                # Serialize proposals for one target and reuse an identical pending change.
                connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (proposal['target_ref'],))
                existing = connection.execute('''SELECT suggestion_id FROM intelligence.suggestions
                    WHERE target_ref=%s AND suggestion_type=%s AND proposed_value=%s AND status='pending'
                    ORDER BY created_at DESC LIMIT 1''',
                    (proposal['target_ref'], proposal['suggestion_type'], Jsonb(proposal['proposed_value']))).fetchone()
                identifier = existing['suggestion_id'] if existing else SuggestionRepository.insert(connection, **proposal)
                connection.execute('INSERT INTO intelligence.asset_assessment_suggestions VALUES (%s,%s) ON CONFLICT DO NOTHING', (job['assessment_id'], identifier))
            status = 'failed' if error_code else 'partial' if partial else 'completed'
            connection.execute('''UPDATE intelligence.asset_assessments SET status=%s,findings=%s,
                error_code=%s,finished_at=now(),lease_until=NULL,claim_token=NULL WHERE assessment_id=%s''',
                (status, Jsonb(findings), error_code, job['assessment_id']))
        return True
