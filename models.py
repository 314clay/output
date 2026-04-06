import re
from typing import Any

from pydantic import BaseModel, field_validator, model_validator

VALID_FORMATS = {
    "text", "image", "html", "chart", "table", "log", "json", "diff",
    "math", "media", "progress", "list",
}

ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,62}[a-zA-Z0-9]$")


class SlotDefinition(BaseModel):
    col: int
    row: int
    width: int = 1
    height: int = 1
    label: str | None = None


class TemplateDefinition(BaseModel):
    columns: int = 2
    row_height: str = "200px"
    gap: str = "20px"
    slots: dict[str, SlotDefinition]


class CreateChannelRequest(BaseModel):
    id: str
    name: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = {}

    @field_validator("id")
    @classmethod
    def validate_id(cls, v):
        if not ID_PATTERN.match(v):
            raise ValueError("id must be 3-64 chars, alphanumeric/hyphens/underscores")
        return v

    @model_validator(mode="after")
    def validate_template(self):
        if "template" in self.metadata:
            TemplateDefinition(**self.metadata["template"])
        return self


class PushItemRequest(BaseModel):
    format: str
    title: str | None = None
    content: dict[str, Any]
    pinned: bool = False
    slot: str | None = None

    @field_validator("format")
    @classmethod
    def validate_format(cls, v):
        if v not in VALID_FORMATS:
            raise ValueError(f"format must be one of: {', '.join(sorted(VALID_FORMATS))}")
        return v


class AppendLogRequest(BaseModel):
    lines: list[str]
    slot: str | None = None
