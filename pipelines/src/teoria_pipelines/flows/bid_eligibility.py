from prefect import flow
from prefect.task_runners import ThreadPoolTaskRunner

from teoria_pipelines.models import LoadSummary
from teoria_pipelines.tasks.bid_eligibility import (
    claim_documents_for_parsing,
    ensure_codex_authentication,
    extract_bid_eligibility_notice,
    normalize_structured_bid_eligibility_notice,
    parse_bid_documents,
    select_notices_for_extraction,
)


@flow(name="입찰공고 첨부문서 파싱")
async def parse_pps_bid_documents(batch_size: int = 100, concurrency: int = 4) -> LoadSummary:
    documents = claim_documents_for_parsing(batch_size)
    return await parse_bid_documents(documents, concurrency)


@flow(name="입찰공고 참가자격 추출", task_runner=ThreadPoolTaskRunner(max_workers=2))
async def extract_pps_bid_eligibility(batch_size: int = 10) -> LoadSummary:
    notices = select_notices_for_extraction(batch_size)
    if not notices:
        return LoadSummary()
    document_notices = [notice for notice in notices if notice["documents"]]
    if document_notices:
        ensure_codex_authentication()
    futures = [
        (extract_bid_eligibility_notice.submit(notice) if notice["documents"]
         else normalize_structured_bid_eligibility_notice.submit(notice))
        for notice in notices
    ]
    results = [future.result(raise_on_failure=False) for future in futures]
    return _extraction_summary(results)


def _extraction_summary(results: list[object]) -> LoadSummary:
    failures = [result for result in results if isinstance(result, BaseException)]
    if failures:
        raise RuntimeError(f"{len(failures)} bid eligibility task(s) failed")
    return LoadSummary(notices=sum(result is True for result in results))
