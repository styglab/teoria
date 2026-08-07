from prefect import flow

from teoria_pipelines.models import LoadSummary
from teoria_pipelines.tasks.bid_eligibility import (
    claim_documents_for_parsing,
    extract_bid_eligibility,
    parse_bid_documents,
    select_notices_for_extraction,
)


@flow(name="입찰공고 첨부문서 파싱")
async def parse_pps_bid_documents(batch_size: int = 100, concurrency: int = 4) -> LoadSummary:
    documents = claim_documents_for_parsing(batch_size)
    return await parse_bid_documents(documents, concurrency)


@flow(name="입찰공고 참가자격 추출")
async def extract_pps_bid_eligibility(batch_size: int = 10) -> LoadSummary:
    notices = select_notices_for_extraction(batch_size)
    return await extract_bid_eligibility(notices)
