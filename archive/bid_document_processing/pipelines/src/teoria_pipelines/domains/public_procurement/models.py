from dataclasses import dataclass

from teoria_pipelines.models import LoadSummary as PipelineLoadSummary


@dataclass(frozen=True, slots=True)
class LoadSummary(PipelineLoadSummary):
    contracts: int = 0
    suppliers: int = 0
    organizations: int = 0
    demand_organizations: int = 0
    notices: int = 0
    license_restrictions: int = 0
    participation_regions: int = 0
    documents: int = 0
    industries: int = 0
    awards: int = 0
    opening_participants: int = 0
    notice_outcomes: int = 0
