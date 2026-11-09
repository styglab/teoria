"""Reuse completed assessment scores only across identical frozen execution contracts."""
from collections import Counter
from copy import deepcopy
import hashlib
import json


def checksum(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def resumable_document_scores(manifest,state,splits,parser_runtime,processor_revision,grader_revision):
    if not manifest.resume_from:return {}
    parent=state['cycles'].get(manifest.resume_from)
    if parent is None or parent.get('cleanup',{}).get('status')!='complete':
        raise ValueError('resume requires a prior assessment with completed cleanup')
    if (parent.get('purpose')!='quality_assessment' or parent.get('baseline_revision')!=processor_revision
            or parent.get('grader_revision')!=grader_revision or parent.get('parser_runtime')!=parser_runtime):
        raise ValueError('resume execution code, grader or parser differs')
    if parent['sampling']['splits']!=splits:raise ValueError('resume split membership differs')
    current={d.document_id:d.model_dump(mode='json') for d in manifest.documents+manifest.regression_documents}
    previous={d['document_id']:d for d in parent['frozen_documents']}
    if current!=previous:raise ValueError('resume source identities or frozen cases differ')
    if any(getattr(manifest,key)!=value for key,value in parent['settings'].items()):
        raise ValueError('resume execution settings differ')
    result={}
    for key,record in parent.get('assessment_document_scores',{}).items():
        score=record['score']
        if key not in current or checksum(score)!=record['sha256']:
            raise ValueError('resume score integrity mismatch')
        if not score['metrics']['failed_documents']:
            result[key]=deepcopy(record)
    return result


def combine_document_scores(scores):
    rows=list(scores)
    if not rows:raise ValueError('no document scores to combine')
    base={key:deepcopy(value) for key,value in rows[0].items() if key not in {'metrics','documents','parser_versions','independent_gold'}}
    for row in rows:
        if any(row[key]!=value for key,value in base.items()):raise ValueError('incompatible document measurement contracts')
    metrics=Counter()
    for row in rows:metrics.update(row['metrics'])
    documents=[d for row in rows for d in row['documents']]
    return {**base,'metrics':dict(metrics),'documents':documents,
        'parser_versions':sorted({v for row in rows for v in row['parser_versions']}),
        'independent_gold':any(v for k,v in metrics.items() if k.endswith('_cases_total')) and all(d['label_status']=='human_reviewed' for d in documents)}
