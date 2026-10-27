"""Source-grounded dictionary proposals exchanged with authenticated authoring APIs."""
from typing import Literal
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, model_validator

import hashlib
import json


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def dictionary_checksum(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def normalized_source_name(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def source_literal_definition(kind, name, owner_name=None):
    if kind == "item_type":
        return f"원문에서 ‘{name}’로 명시한 물품 유형."
    return f"‘{owner_name}’의 ‘{name}’에 관한 규격 특성."


class DictionarySourceNode(Record):
    locator: str = Field(min_length=1, max_length=1000)
    text: str = Field(max_length=100000)


class DictionarySource(Record):
    document_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parser_version: str = Field(min_length=1, max_length=100)
    nodes: list[DictionarySourceNode] = Field(min_length=1, max_length=20000)

    @model_validator(mode="after")
    def unique_locations(self):
        refs = [n.locator for n in self.nodes]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate source locator")
        return self


class DictionaryEvidence(Record):
    document_id: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: str
    quote: str = Field(min_length=1, max_length=100000)


class DictionaryCandidate(Record):
    candidate_key: str = Field(min_length=1, max_length=200)
    kind: Literal["item_type", "characteristic"]
    preferred_name: str = Field(min_length=1, max_length=300)
    definition: str = Field(min_length=1, max_length=2000)
    owner_candidate_key: str | None = None
    owner_entry_id: str | None = None
    value_kind: Literal["number", "text", "range", "tolerance", "dimensions", "set", "expression", "relative", "all", "any"] | None = None
    origin_ref: str = Field(min_length=1, max_length=1000)
    evidence: list[DictionaryEvidence] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def candidate_shape(self):
        if self.kind == "item_type" and any([self.owner_candidate_key, self.owner_entry_id, self.value_kind]):
            raise ValueError("item types cannot declare a characteristic owner or value kind")
        if self.kind == "characteristic":
            if bool(self.owner_candidate_key) == bool(self.owner_entry_id) or self.value_kind is None:
                raise ValueError("characteristics require one owner and a value kind")
        return self


class DictionarySubmission(Record):
    schema_version: Literal[1] = 1
    auto_approve: bool = True
    sources: list[DictionarySource] = Field(min_length=1, max_length=100)
    candidates: list[DictionaryCandidate] = Field(max_length=5000)

    @model_validator(mode="after")
    def bounded_unambiguous_input(self):
        ids = [c.candidate_key for c in self.candidates]
        docs = [s.document_id for s in self.sources]
        if len(ids) != len(set(ids)) or len(docs) != len(set(docs)):
            raise ValueError("duplicate candidate or document ID")
        if sum(len(n.text) for s in self.sources for n in s.nodes) > 8_000_000:
            raise ValueError("dictionary evidence exceeds the request budget")
        if sum(len(e.quote) for c in self.candidates for e in c.evidence) > 8_000_000:
            raise ValueError("dictionary candidate evidence exceeds the request budget")
        return self
