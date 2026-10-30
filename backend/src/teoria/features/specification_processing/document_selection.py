"""Bounded acquisition and an immutable record of selected specification candidates."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import PurePath
import re
from urllib.parse import unquote, urlsplit
from uuid import uuid4
import httpx
from prefect import task
from prefect.cache_policies import NO_CACHE
from teoria.features.specification_processing.models import SourceDocument
from teoria.features.specification_processing.storage.artifact_store import artifact_store, read_uri
from teoria.features.specification_processing.storage.notice_candidates import notice_candidates

MAX_BYTES=25*1024*1024


def supported_content(data, filename):
    suffix=PurePath(filename).suffix.lower()
    if suffix=='.pdf':return data.startswith(b'%PDF-')
    if suffix=='.hwp':return data.startswith(bytes.fromhex('d0cf11e0a1b11ae1'))
    return suffix in {'.hwpx','.docx','.xlsx','.pptx'} and data.startswith(b'PK\x03\x04')


async def acquire_source(uri):
    SourceDocument.safe_uri(uri)
    if urlsplit(uri).scheme!='https':
        data=await read_uri(uri)
        if len(data)>MAX_BYTES:raise ValueError('source_size_limit')
        return data
    # Stream attachments so an error page or oversized body cannot fill memory.
    async with httpx.AsyncClient(timeout=45,follow_redirects=False) as client:
        for _ in range(4):
            async with client.stream('GET',uri) as response:
                if response.is_redirect:
                    target=str(response.url.join(response.headers['location']))
                    SourceDocument.safe_uri(target)
                    if urlsplit(target).scheme!='https':raise ValueError('insecure_redirect')
                    uri=target;continue
                response.raise_for_status();data=bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data)>MAX_BYTES:raise ValueError('source_size_limit')
                return bytes(data)
        raise ValueError('too_many_redirects')


@task(name='대상 규격서 선정·확보', persist_result=False, cache_policy=NO_CACHE, retries=0)
async def select_specifications(parameters, *, repository=None, acquire=None, today=None):
    acquire=acquire or acquire_source
    execution=parameters.execution
    from prefect.runtime import flow_run
    run_id=execution.run_id or 'spec_'+str(flow_run.id or uuid4().hex).replace('-','')
    import os
    root=execution.artifact_root or os.getenv('TEORIA_SPECIFICATION_ARTIFACT_ROOT','s3://teoria-artifacts')
    day=today or datetime.now(timezone.utc).date()
    end=parameters.selection.date_to or day
    start=parameters.selection.date_from or end-timedelta(days=parameters.selection.lookback_days)
    if start>end:raise ValueError('resolved date range is reversed')
    prefix='specification_processing/'+run_id+'/'
    # Generated IDs are fixed before extraction; explicit IDs can replay the same selection.
    fingerprint=hashlib.sha256(parameters.model_dump_json().encode()).hexdigest()
    async with artifact_store(root) as store:
        try:frozen=json.loads(await store.get(prefix+'document_selection.json'))
        except FileNotFoundError:frozen=None
        if frozen:
            if frozen['input_fingerprint']!=fingerprint:raise ValueError('run_id belongs to another selection')
            return frozen
        attempts=[];selected=[];hashes=set();scanned=0
        if parameters.documents is not None:
            notices=[{'notice_number':d.notice_number,'explicit':d} for d in parameters.documents]
        else:
            notices=await (repository or notice_candidates)(parameters.classification_code,start,end+timedelta(days=1),parameters.selection.max_notices_to_scan)
        for notice in notices:
            if len(selected)>=parameters.target_specifications:break
            scanned+=1
            if 'explicit' in notice:
                candidates=[notice['explicit']]
            else:
                candidates=[];payload=notice['source_payload']
                codes={str(i.get('code')) for i in notice.get('purchase_items') or [] if i.get('code')}
                if notice.get('procurement_classification_number'):codes.add(notice['procurement_classification_number'])
                if codes-{parameters.classification_code}:
                    attempts.append({'notice_number':notice['notice_number'],'reason':'mixed_item_classifications'});continue
                for slot in range(1,11):
                    uri=payload.get(f'ntceSpecDocUrl{slot}')
                    name=payload.get(f'ntceSpecFileNm{slot}')
                    if not uri:continue
                    if not name:name=unquote(PurePath(urlsplit(uri).path).name)
                    # Conservative filename evidence; extracted content remains subject to quality review.
                    if not re.search(r'규격|시방|사양|specification',name,re.I):continue
                    try:
                        candidate=SourceDocument(document_id='doc_'+hashlib.sha256(
                            (notice['notice_number']+':'+notice['notice_order']+':'+str(slot)).encode()).hexdigest()[:24],
                            notice_number=notice['notice_number'],source_uri=uri,filename=name)
                    except ValueError:
                        attempts.append({'notice_number':notice['notice_number'],'slot':slot,'reason':'unsupported_attachment'});continue
                    candidates.append(candidate)
            if not candidates:
                attempts.append({'notice_number':notice['notice_number'],'reason':'no_specification_candidate'})
            for candidate in candidates:
                if len(selected)>=parameters.target_specifications:break
                record={'notice_number':candidate.notice_number,'document_id':candidate.document_id}
                try:
                    data=await acquire(candidate.source_uri)
                    if len(data)>MAX_BYTES:raise ValueError('source_size_limit')
                    digest=hashlib.sha256(data).hexdigest()
                    if candidate.sha256 and candidate.sha256!=digest:raise ValueError('source_checksum_mismatch')
                    if not supported_content(data,candidate.filename):raise ValueError('unsupported_document_content')
                    if digest in hashes:
                        attempts.append({**record,'reason':'duplicate_content'});continue
                    ref=await store.put(prefix+'selected_sources/'+candidate.document_id+PurePath(candidate.filename).suffix.lower(),data,'application/octet-stream')
                    selected.append({**candidate.model_dump(mode='json'),'source_uri':ref.uri,'sha256':digest,
                        'origin_uri':candidate.source_uri,'artifact':ref.model_dump(mode='json'),
                        'notice_order':notice.get('notice_order'),'source_record_hash':notice.get('source_record_hash'),
                        'notice_published_at':str(notice.get('notice_published_at')) if notice.get('notice_published_at') else None})
                    hashes.add(digest)
                except (httpx.HTTPError,OSError,ValueError):
                    attempts.append({**record,'reason':'source_unavailable_or_invalid'})
        report={'run_id':run_id,'artifact_root':root,'input_fingerprint':fingerprint,
            'classification_code':parameters.classification_code,'date_from':str(start),'date_to':str(end),
            'target_specifications':parameters.target_specifications,'acquired_specifications':len(selected),
            'notices_scanned':scanned if parameters.documents is None else None,
            'explicit_files_checked':scanned if parameters.documents is not None else None,
            'shortfall':max(0,parameters.target_specifications-len(selected)),
            'stop_reason':'target_reached' if len(selected)>=parameters.target_specifications else
                'scan_limit_reached' if parameters.documents is None and scanned>=parameters.selection.max_notices_to_scan else 'available_candidates_exhausted',
            'selected':selected,'excluded':attempts,'exclusion_summary':dict(Counter(a['reason'] for a in attempts)),
            'count_unit':'deduplicated_downloaded_files; parsing_and_semantics_not_yet_verified'}
        await store.put(prefix+'document_selection.json',(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
        return report
