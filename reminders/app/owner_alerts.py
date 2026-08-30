"""Validated owner-change events and concise Telegram rendering."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


Scalar = str | int | float | bool | None
SafeText = Annotated[str, Field(min_length=1, max_length=500)]
ShortString = Annotated[str, Field(max_length=500)]
StringList = Annotated[list[ShortString], Field(max_length=20)]
PublicValue = Scalar | StringList

ALLOWED_SOURCE_HOSTS = (
    "americanexpress.com",
    "pocket-concierge.jp",
    "diningcity.asia",
    "go.amex",
)


class OwnerAlertChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Annotated[str, Field(min_length=1, max_length=80)]
    before: PublicValue
    after: PublicValue


class OwnerAlertSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Annotated[str, Field(min_length=1, max_length=40)]
    fields: Annotated[dict[str, PublicValue], Field(max_length=40)]


class OwnerAlertEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")]
    transition_id: Annotated[str | None, Field(pattern=r"^[0-9a-f]{20}$")] = None
    stream_id: Annotated[str | None, Field(pattern=r"^[0-9a-f]{20}$")] = None
    occurrence: Annotated[int | None, Field(ge=1)] = None
    owner_delivery_state: Annotated[str | None, Field(max_length=40)] = None
    owner_delivery_recorded_at: datetime | None = None
    program: Annotated[str, Field(min_length=1, max_length=80)]
    program_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,80}$")]
    route: Annotated[str, Field(pattern=r"^#/[a-z0-9/_-]{1,160}$")]
    kind: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    subject: SafeText
    detected_at: datetime
    status: Literal["published", "review_required", "rejected"]
    before: OwnerAlertSnapshot
    after: OwnerAlertSnapshot
    changes: Annotated[list[OwnerAlertChange], Field(min_length=1, max_length=20)]
    source_url: Annotated[str, Field(min_length=8, max_length=500)]
    reviewed_at: datetime | None = None
    review_note: Annotated[str | None, Field(max_length=500)] = None

    @field_validator("detected_at", "reviewed_at", "owner_delivery_recorded_at")
    @classmethod
    def timestamps_are_aware_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("source_url")
    @classmethod
    def source_url_is_reviewed_https(cls, value: str) -> str:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise ValueError("source_url must be a reviewed HTTPS source")
        if not any(host == allowed or host.endswith(f".{allowed}") for allowed in ALLOWED_SOURCE_HOSTS):
            raise ValueError("source_url host is not allowed")
        return value

    def delivery_payload(self) -> dict:
        return {
            "id": self.id,
            "program": self.program,
            "program_id": self.program_id,
            "route": self.route,
            "kind": self.kind,
            "subject": self.subject,
            "detected_at": self.detected_at.isoformat(),
            "changes": [change.model_dump(mode="json") for change in self.changes],
            "source_url": self.source_url,
        }

    def digest(self) -> str:
        encoded = json.dumps(
            self.delivery_payload(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class OwnerAlertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: OwnerAlertEvent


def _short(value: PublicValue, limit: int = 240) -> str:
    if value is None:
        rendered = "Not available"
    elif isinstance(value, bool):
        rendered = "Yes" if value else "No"
    elif isinstance(value, list):
        rendered = ", ".join(value)
    else:
        rendered = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(rendered) <= limit:
        return rendered
    return rendered[: limit - 1].rstrip() + "…"


def format_owner_alert(event: OwnerAlertEvent, explorer_base_url: str) -> str:
    kind = event.kind.replace("_", " ").title()
    lines = [f"Amex Explorer update · {kind}", "", event.program, event.subject]
    detected = event.detected_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    explorer_url = f"{explorer_base_url.rstrip('/')}/{event.route}"
    footer = "\n".join(
        [f"Detected: {detected}", f"Source: {event.source_url}", f"Explorer: {explorer_url}"]
    )
    body_budget = 3900 - len(footer) - 2
    included = 0
    for change in event.changes:
        block = [
            "",
            change.field,
            f"Before: {_short(change.before)}",
            f"After: {_short(change.after)}",
        ]
        candidate = "\n".join([*lines, *block])
        if len(candidate) > body_budget - 40:
            break
        lines.extend(block)
        included += 1
    remaining = len(event.changes) - included
    if remaining:
        lines.extend(["", f"…and {remaining} more change(s)"])
    body = "\n".join(lines)
    if len(body) > body_budget:
        body = body[: body_budget - 1].rstrip() + "…"
    return f"{body}\n\n{footer}"
