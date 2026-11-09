from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Provenance(BaseModel):
    kind: Literal["source", "execution"]
    source: str
    operation: str
    mapping: str
    observed_at: datetime
    record_keys: list[str]
