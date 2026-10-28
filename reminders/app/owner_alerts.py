"""Validated owner-change events and concise Telegram rendering."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


Scalar = str | int | float | bool | None
SafeText = Annotated[str, Field(min_length=1, max_length=500)]
ShortString = Annotated[str, Field(max_length=500)]
StringList = Annotated[list[ShortString], Field(max_length=20)]


class CoverageValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    covered: Annotated[int, Field(ge=0)]
    total: Annotated[int, Field(ge=0)]
    unavailable: Annotated[int, Field(ge=0)]
    percent: Annotated[float, Field(ge=0, le=100)]


PublicValue = Scalar | StringList | CoverageValue

ALLOWED_SOURCE_HOSTS = (
    "americanexpress.com",
    "pocket-concierge.jp",
    "diningcity.asia",
    "diningcity.sg",
    "go.amex",
    "google.com",
    "tabelog.com",
)


class OwnerAlertChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Annotated[str, Field(min_length=1, max_length=80)]
    before: PublicValue
    after: PublicValue

    @field_validator("field")
    @classmethod
    def field_has_no_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value):
            raise ValueError("change field must not contain control characters")
        return value


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
    retracted_at: datetime | None = None
    retraction_note: Annotated[str | None, Field(max_length=500)] = None
    corrected_by: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")] = None
    corrects: Annotated[list[str], Field(max_length=20)] = Field(default_factory=list)
    program: Annotated[str, Field(min_length=1, max_length=80)]
    program_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,80}$")]
    route: Annotated[
        str,
        Field(pattern=r"^#/[a-z0-9/_-]{1,160}(?:\?venue=[a-z0-9-]{1,80})?$"),
    ]
    kind: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    subject: SafeText
    detected_at: datetime
    status: Literal["published", "review_required", "rejected", "retracted"]
    before: OwnerAlertSnapshot
    after: OwnerAlertSnapshot
    changes: Annotated[list[OwnerAlertChange], Field(min_length=1, max_length=20)]
    source_url: Annotated[str, Field(min_length=8, max_length=500)]
    reviewed_at: datetime | None = None
    review_note: Annotated[str | None, Field(max_length=500)] = None

    @field_validator("subject")
    @classmethod
    def subject_has_no_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value):
            raise ValueError("subject must not contain control characters")
        return value

    @field_validator(
        "detected_at", "reviewed_at", "owner_delivery_recorded_at", "retracted_at"
    )
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


OWNER_ALERT_BATCH_LIMIT = 500
# 500 events at ~2.6 KB each is ~1.3 MB; the sender splits above 1.5 MB.
OWNER_ALERT_BATCH_MAX_BYTES = 2 * 1024 * 1024


class OwnerAlertBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: Annotated[list, Field(max_length=OWNER_ALERT_BATCH_LIMIT)]


def _short(value: PublicValue, limit: int = 240) -> str:
    if value is None:
        rendered = "Not available"
    elif isinstance(value, CoverageValue):
        rendered = (
            f"{value.covered}/{value.total} ({value.percent:g}%), "
            f"{value.unavailable} unavailable"
        )
    elif isinstance(value, bool):
        rendered = "Yes" if value else "No"
    elif isinstance(value, list):
        rendered = ", ".join(value)
    else:
        rendered = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(rendered) <= limit:
        return rendered
    cut = rendered[: limit - 1]
    # Prefer a clause break, then a word break; CJK text without spaces cuts hard.
    for separator in (", ", " "):
        boundary = cut.rfind(separator)
        if boundary >= limit // 2:
            cut = cut[:boundary]
            break
    return cut.rstrip(" ,") + "…"


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


DIGEST_LIMIT = 3900
DIGEST_ITEM_WIDTH = 160
BULK_THRESHOLD = 20
KIND_ORDER = {"added": 0, "removed": 1}
HASH_FIELD = re.compile(r"sha-?256|hash|fingerprint|version", re.IGNORECASE)
COUNT_NOUNS = {"Record count": "records", "Mapped count": "mapped"}
PROGRAM_NOUNS = {"plat-stay": "hotels"}
COVERAGE_TEXT = re.compile(r"^(\d+/\d+)\b")
REVIEW_FIELDS = {"Source state", "Review", "Review items"}


def _is_number(value: PublicValue) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _change_text(change: OwnerAlertChange, width: int = 60) -> str:
    if _is_number(change.before) and _is_number(change.after):
        noun = COUNT_NOUNS.get(change.field, change.field.lower())
        if noun.endswith(" count"):
            noun = noun.removesuffix(" count") + "s"
        return f"{change.before} → {change.after} {noun}"
    return f"{change.field} {_short(change.before, width)} → {_short(change.after, width)}"


def _covered(value: PublicValue) -> str | None:
    if isinstance(value, CoverageValue):
        return f"{value.covered}/{value.total}"
    match = COVERAGE_TEXT.match(value) if isinstance(value, str) else None
    return match.group(1) if match else None


def _review_text(changes: dict[str, OwnerAlertChange]) -> str | None:
    review, state = changes.get("Review"), changes.get("Source state")
    if (review and review.after == "required") or (state and state.after == "review_required"):
        items = changes.get("Review items")
        count = items.after if items and _is_number(items.after) else None
        return "needs review" + (f" ({count} item{'' if count == 1 else 's'})" if count else "")
    if (review and review.before == "required") or (state and state.before == "review_required"):
        return "review cleared"
    return None


def _meta_item(event: OwnerAlertEvent) -> str:
    label = event.subject.strip()
    if label.lower().startswith(event.program.lower()):
        label = label[len(event.program) :].strip()
    label = label[:1].upper() + label[1:] if label else "Source"
    changes = {change.field: change for change in event.changes}
    review = _review_text(changes)
    parts = [review] if review else []
    for change in event.changes:
        if HASH_FIELD.search(change.field) or (review and change.field in REVIEW_FIELDS):
            continue
        before, after = _covered(change.before), _covered(change.after)
        if change.field == "Coverage" and before and after:
            parts.append(f"{before} → {after} covered")
        elif change.field == "Source state" and isinstance(change.after, str):
            parts.append(f"{str(change.before).replace('_', ' ')} → {change.after.replace('_', ' ')}")
        else:
            parts.append(_change_text(change))
    if parts:
        return f"~ {label}: {', '.join(parts)}"
    hashed = any(HASH_FIELD.search(change.field) for change in event.changes)
    return f"~ {label}: {'official records' if hashed else 'records'} changed"


def _digest_text(event: OwnerAlertEvent) -> str:
    if event.kind == "added":
        return f"+ {event.subject.strip()}"
    if event.kind == "removed":
        return f"− {event.subject.strip()}"
    if event.kind.startswith("source_"):
        return _meta_item(event)
    return f"~ {event.subject.strip()}: " + ", ".join(change.field for change in event.changes)


def _merged_line(text: str, count: int) -> str:
    suffix = f" (×{count})" if count > 1 else ""
    return _short(text, DIGEST_ITEM_WIDTH - len(suffix)) + suffix


def _bulk_lines(members: list[OwnerAlertEvent], fields: tuple[str, ...]) -> list[str]:
    noun = PROGRAM_NOUNS.get(members[0].program_id, "restaurants")
    head = (
        f"⚠ {len(members)} {noun} changed {', '.join(fields)} at once. "
        "Possible source glitch; check before trusting."
    )
    examples = [
        f"~ {event.subject.strip()}: " + ", ".join(_change_text(c, 40) for c in event.changes)
        for event in members[:2]
    ]
    return [_short(line, DIGEST_ITEM_WIDTH) for line in (_short(head, 400), *examples)]


def _kind_key(kind: str) -> tuple[int, str]:
    return (KIND_ORDER.get(kind, 2), kind)


def _program_units(events: list[OwnerAlertEvent]) -> list[tuple[list[str], int]]:
    """Lines plus event count per unit; one item of every kind leads."""
    groups: dict[tuple[str, tuple[str, ...]], list[OwnerAlertEvent]] = {}
    for event in events:
        fields = tuple(change.field for change in event.changes)
        groups.setdefault((event.kind, fields), []).append(event)
    units, repeats = [], Counter()
    for (kind, fields), members in groups.items():
        if len(members) >= BULK_THRESHOLD and kind not in KIND_ORDER:
            units.append((_kind_key(kind), 0, _bulk_lines(members, fields), len(members)))
        else:
            repeats.update((_kind_key(kind), _digest_text(event)) for event in members)
    # Identical lines collapse into one with a count, in first-seen order.
    units.extend((key, 1, [_merged_line(text, n)], n) for (key, text), n in repeats.items())
    units.sort(key=lambda unit: unit[:2])
    leads, rest, seen = [], [], set()
    for key, _bulk, lines, count in units:
        (rest if key in seen else leads).append((lines, count))
        seen.add(key)
    return leads + rest


def format_owner_digest(events: list[OwnerAlertEvent], explorer_base_url: str) -> str:
    total = len(events)
    header = f"Amex Explorer · {total} update{'' if total == 1 else 's'}"
    groups: dict[str, list[OwnerAlertEvent]] = {}
    for event in events:
        groups.setdefault(event.program, []).append(event)
    base = explorer_base_url.rstrip("/")
    sections = []
    for program in sorted(groups):
        items = groups[program]
        counts = Counter(event.kind for event in items)
        count_text = ", ".join(
            f"{counts[kind]} {kind.replace('_', ' ')}" for kind in sorted(counts, key=_kind_key)
        )
        if len(items) == 1 and "?venue=" in items[0].route:
            route = items[0].route
        else:
            # Most common route wins; ties go to the first in sorted order.
            routes = Counter(event.route.split("?", 1)[0] for event in items)
            route = min(routes, key=lambda r: (-routes[r], r))
        sections.append(
            (f"{_short(program, 80)} · {count_text}", _program_units(items), len(items),
             f"Explorer: {base}/{route}")
        )
    shown = [0] * len(sections)

    def render() -> str:
        lines = [header]
        for (title, units, count, link), visible in zip(sections, shown):
            lines.extend(["", title])
            for unit_lines, _count in units[:visible]:
                lines.extend(unit_lines)
            hidden = count - sum(unit_count for _lines, unit_count in units[:visible])
            if hidden:
                lines.append(f"…and {hidden} more")
            lines.append(link)
        return "\n".join(lines)

    message = render()
    if len(message) > DIGEST_LIMIT:
        return message[: DIGEST_LIMIT - 1].rstrip() + "…"
    # Round-robin one unit per program until the budget is spent.
    growing = [index for index, section in enumerate(sections) if section[1]]
    while growing:
        for index in list(growing):
            shown[index] += 1
            candidate = render()
            if len(candidate) <= DIGEST_LIMIT:
                message = candidate
            else:
                shown[index] -= 1
            if len(candidate) > DIGEST_LIMIT or shown[index] == len(sections[index][1]):
                growing.remove(index)
    return message
