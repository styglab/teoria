"""Async Data DB execution metadata; document bodies remain in artifact storage."""
from __future__ import annotations
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from teoria.integrations.data_operations.persistence.connection import connect
from teoria.integrations.data_operations.settings import bootstrap_pipeline_settings
from teoria.features.specification_processing.models import ArtifactRef,RunResult,SpecificationRun,StandardReference

class SpecificationRepository:
    def __init__(self,database_url):
        if not database_url:raise ValueError('TEORIA_PIPELINE_DATA_DATABASE_URL is required')
        self.database_url=database_url

    @classmethod
    def from_environment(cls):
        return cls(bootstrap_pipeline_settings().data_database_url)

    async def register_extraction(self, run_id, reference, corpus):
        """Phase-05 durable references only; final run completion remains separate."""
        async with connect(self.database_url,row_factory=dict_row) as connection:
            run=await(await connection.execute('SELECT status FROM public_procurement.specification_processing_runs WHERE run_id=%s FOR UPDATE',(run_id,))).fetchone()
            if run is None:return False
            if run['status']!='running':raise ValueError('run is not active')
            await connection.execute('''INSERT INTO public_procurement.specification_processing_artifacts
                (run_id,object_key,uri,sha256,size_bytes,media_type) VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (run_id,object_key) DO NOTHING''',
                (run_id,reference['key'],reference['uri'],reference['sha256'],reference['size_bytes'],reference.get('media_type','application/json')))
            stored=await(await connection.execute('SELECT uri,sha256 FROM public_procurement.specification_processing_artifacts WHERE run_id=%s AND object_key=%s',(run_id,reference['key']))).fetchone()
            if stored['uri']!=reference['uri'] or stored['sha256']!=reference['sha256']:
                raise ValueError('extraction reference is immutable')
            for d in corpus['documents']:
                await connection.execute('''INSERT INTO public_procurement.specification_processing_documents
                    (run_id,document_id,notice_number,status,source_sha256,result_summary)
                    VALUES (%s,%s,%s,'extracted',%s,%s) ON CONFLICT (run_id,document_id) DO NOTHING''',
                    (run_id,d['document_id'],d.get('notice_number'),d['source']['sha256'],Jsonb({'phase':'extraction_stored'})))
                stored_document=await(await connection.execute('SELECT source_sha256 FROM public_procurement.specification_processing_documents WHERE run_id=%s AND document_id=%s',
                    (run_id,d['document_id']))).fetchone()
                if stored_document['source_sha256']!=d['source']['sha256']:
                    raise ValueError('document source reference is immutable')
            return True

    async def find_extractions(self, source_hashes, *, exclude_run, limit=100):
        async with connect(self.database_url,row_factory=dict_row) as connection:
            return await(await connection.execute('''SELECT DISTINCT ON (d.source_sha256,r.classification_code)
                d.source_sha256,d.run_id,r.classification_code,a.uri,a.sha256,n.uri AS normalized_uri,n.sha256 AS normalized_sha256
                FROM public_procurement.specification_processing_documents d
                JOIN public_procurement.specification_processing_runs r USING(run_id)
                JOIN public_procurement.specification_processing_artifacts a ON a.run_id=d.run_id
                  AND a.object_key='specification_processing/'||d.run_id||'/extracted.json'
                LEFT JOIN public_procurement.specification_processing_artifacts n ON n.run_id=d.run_id
                  AND n.object_key='specification_processing/'||d.run_id||'/normalized.json'
                WHERE d.source_sha256=ANY(%s) AND d.run_id<>%s AND d.status IN ('extracted','partial')
                  AND r.status IN ('completed','partial','failed')
                ORDER BY d.source_sha256,r.classification_code,(n.uri IS NOT NULL) DESC,r.finished_at DESC NULLS LAST,r.started_at DESC
                LIMIT %s''',(sorted(source_hashes),exclude_run,limit+1))).fetchall()

    async def find_accepted_contexts(self, contexts):
        if not contexts:return []
        async with connect(self.database_url,row_factory=dict_row) as connection:
            return await(await connection.execute('''SELECT DISTINCT c.source_entry_id,c.context_sha256,c.definition_revision_id
                FROM public_procurement.specification_dictionary_contexts c
                JOIN jsonb_to_recordset(%s::jsonb) AS q(source_entry_id text,context_sha256 text,definition_revision_id text)
                USING(source_entry_id,context_sha256,definition_revision_id)
                JOIN public_procurement.specification_processing_runs r USING(run_id)
                WHERE r.status IN ('completed','partial')''',(Jsonb(contexts),))).fetchall()

    async def start(self,request:SpecificationRun,fingerprint:str):
        async with connect(self.database_url,row_factory=dict_row) as connection:
            inserted=await(await connection.execute('''INSERT INTO public_procurement.specification_processing_runs
                (run_id,input_fingerprint,mode,classification_code,artifact_root,status)
                VALUES (%s,%s,%s,%s,%s,'running') ON CONFLICT DO NOTHING RETURNING run_id''',
                (request.run_id,fingerprint,request.mode,request.classification_code,request.artifact_root))).fetchone()
            if inserted:
                for document in request.documents:
                    await connection.execute("""INSERT INTO public_procurement.specification_processing_inputs
                        (run_id,document_id,filename,source_uri,source_sha256,notice_number) VALUES (%s,%s,%s,%s,%s,%s)""",
                        (request.run_id,document.document_id,document.filename,document.source_uri,document.sha256,document.notice_number))
                return None
            row=await(await connection.execute('SELECT * FROM public_procurement.specification_processing_runs WHERE run_id=%s FOR UPDATE',(request.run_id,))).fetchone()
            if row['input_fingerprint']!=fingerprint:raise ValueError('run_id already belongs to different inputs or processing code')
            if row['status'] in {'completed','partial'} or (row['status']=='failed' and row['summary']):
                return await self._load_result(connection,row)
            if row['status']=='running':raise ValueError('run_id is already running')
            await connection.execute("UPDATE public_procurement.specification_processing_runs SET status='running',error_code=NULL,finished_at=NULL,updated_at=now() WHERE run_id=%s",(request.run_id,))
            return None

    async def _load_result(self,connection,row):
        artifacts=await(await connection.execute('SELECT * FROM public_procurement.specification_processing_artifacts WHERE run_id=%s ORDER BY object_key',(row['run_id'],))).fetchall()
        documents=await(await connection.execute('SELECT document_id,notice_number,status,source_sha256,result_summary FROM public_procurement.specification_processing_documents WHERE run_id=%s ORDER BY document_id',(row['run_id'],))).fetchall()
        standard=StandardReference(uri=row['standard_uri'],sha256=row['standard_sha256']) if row['standard_uri'] else None
        return RunResult(run_id=row['run_id'],status=row['status'],summary=row['summary'],standard=standard,
            artifacts=[ArtifactRef(key=a['object_key'],uri=a['uri'],sha256=a['sha256'],size_bytes=a['size_bytes'],media_type=a['media_type']) for a in artifacts],
            document_results=[dict(d) for d in documents])

    async def complete(self,result:RunResult):
        # Artifact upload must finish before this one transaction becomes the completion checkpoint.
        async with connect(self.database_url) as connection:
            row=await(await connection.execute("SELECT status FROM public_procurement.specification_processing_runs WHERE run_id=%s FOR UPDATE",(result.run_id,))).fetchone()
            if row is None or row[0]!='running':raise ValueError('run is not active')
            for artifact in result.artifacts:
                await connection.execute('''INSERT INTO public_procurement.specification_processing_artifacts
                    (run_id,object_key,uri,sha256,size_bytes,media_type) VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (run_id,object_key) DO UPDATE SET uri=EXCLUDED.uri,sha256=EXCLUDED.sha256,size_bytes=EXCLUDED.size_bytes,media_type=EXCLUDED.media_type''',
                    (result.run_id,artifact.key,artifact.uri,artifact.sha256,artifact.size_bytes,artifact.media_type))
            for document in result.document_results:
                await connection.execute('''INSERT INTO public_procurement.specification_processing_documents
                    (run_id,document_id,notice_number,status,source_sha256,result_summary) VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (run_id,document_id) DO UPDATE SET status=EXCLUDED.status,result_summary=EXCLUDED.result_summary''',
                    (result.run_id,document['document_id'],document.get('notice_number'),document['status'],document['source_sha256'],Jsonb(document['result_summary'])))
                for context in document['result_summary'].get('dictionary_contexts',[]):
                    await connection.execute('''INSERT INTO public_procurement.specification_dictionary_contexts
                        (run_id,document_id,source_entry_id,context_sha256,definition_revision_id)
                        VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                        (result.run_id,document['document_id'],context['source_entry_id'],context['context_sha256'],context['definition_revision_id']))
            await connection.execute('''UPDATE public_procurement.specification_processing_runs SET status=%s,
                standard_uri=%s,standard_sha256=%s,summary=%s,finished_at=now(),updated_at=now(),error_code=NULL WHERE run_id=%s''',
                (result.status,result.standard.uri if result.standard else None,result.standard.sha256 if result.standard else None,Jsonb(result.summary),result.run_id))

    async def fail(self,run_id,error_code):
        async with connect(self.database_url) as connection:
            await connection.execute("UPDATE public_procurement.specification_processing_runs SET status='failed',error_code=%s,finished_at=now(),updated_at=now() WHERE run_id=%s AND status='running'",(error_code,run_id))
