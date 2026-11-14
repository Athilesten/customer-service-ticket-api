from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .models import Priority, Status

SLAState = Literal["on_track", "due_soon", "breached", "met", "missed"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=120)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=5000)]
Handle = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_-]{1,50}$")]
Version = Annotated[int, Field(strict=True, ge=1, le=2_147_483_646)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TicketCreate(Input):
    title: Title
    description: Description
    priority: Priority = Priority.NORMAL

    @field_validator("title", "description")
    @classmethod
    def reject_unstorable_text(cls, value):
        if "\x00" in value:
            raise ValueError("NUL characters are forbidden")
        value.encode("utf-8")
        return value


class Change(Input):
    expected_version: Version


class Assignment(Change):
    assignee: Handle


class Reprioritize(Change):
    priority: Priority


class Transition(Change):
    status: Status


class Page(Input):
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=100_000)


class Search(Page):
    q: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                        max_length=100, pattern=r"^[^\x00]+$")] | None = None
    status: Status | None = None
    priority: Priority | None = None
    assignee: Handle | None = None
    assignment: Literal["assigned", "unassigned"] | None = None
    sort: Literal["newest", "resolution_due"] = "newest"
    resolution_sla: SLAState | None = None
