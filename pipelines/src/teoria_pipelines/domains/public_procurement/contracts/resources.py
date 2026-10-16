from teoria_pipelines.domains.public_procurement.contracts.repository import (
    ContractRepository,
)
from teoria_pipelines.settings import bootstrap_pipeline_settings


def _store() -> ContractRepository:
    return ContractRepository(bootstrap_pipeline_settings().data_database_url or "")
