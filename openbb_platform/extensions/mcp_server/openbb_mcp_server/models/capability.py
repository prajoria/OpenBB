"""Validated metadata contracts for MCP capability inventories."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterator, Mapping
from typing import Annotated, Any, Literal, get_args
from urllib.parse import unquote, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
Surface = Literal["platform", "workspace", "agents", "daytrade"]
OwnerLane = Literal[
    "A-Data",
    "B-Analytics",
    "C-App+Paper",
    "D-Widgets+QA",
    "PM",
    "QA",
]
Disposition = Literal[
    "direct",
    "workspace_indirect",
    "metadata_only",
    "restricted",
    "unimplemented",
]
AccessClass = Literal[
    "public_metadata",
    "provider_read",
    "private_portfolio_read",
    "filesystem_write",
    "cache_maintenance",
    "job_control",
    "workspace_mutation",
    "financial_mutation",
]
Persistence = Literal[
    "dedicated",
    "ttl",
    "fallback_none",
    "not_applicable",
    "unverified",
]

_SUPPORTED_DISPOSITIONS = get_args(Disposition)
_APPROVED_DISPOSITIONS = frozenset(
    {"direct", "workspace_indirect", "metadata_only"}
)
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_QUALIFIED_SYMBOL_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
)
_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(?:api[_-]?key|password|passwd|secret|access[_-]?token|token)"
        r"\s*[:=]\s*\S+"
    ),
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+\S+"),
    re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)[a-z][a-z0-9+.-]*://[^/@:\s]+:[^/@\s]+@"),
)


def _contains_secret_shape(value: str) -> bool:
    """Return whether *value* resembles credential material."""
    return any(pattern.search(value) for pattern in _SECRET_PATTERNS)


def _validate_safe_text(value: str, *, field_name: str) -> str:
    """Validate nonempty metadata text without leaking its content in errors."""
    if not value or value != value.strip():
        raise ValueError(f"{field_name} entries must be nonempty and trimmed")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} entries cannot contain control characters")
    if _contains_secret_shape(value):
        raise ValueError(f"{field_name} entries cannot contain credential-shaped values")
    return value


def _decoded_path(value: str) -> str:
    """Decode nested percent encoding to a stable canonical value."""
    decoded = value
    for _ in range(len(value) + 1):
        candidate = unquote(decoded)
        if candidate == decoded:
            return decoded
        decoded = candidate
    raise ValueError("percent encoding did not converge to a stable value")


def sanitized_validation_errors(error: ValidationError) -> list[dict[str, Any]]:
    """Return structured validation errors without rejected inputs or context."""
    sanitized = []
    for detail in error.errors(include_input=False, include_context=False):
        clean_detail = dict(detail)
        clean_detail["loc"] = tuple(
            "<rejected-field>"
            if isinstance(component, str) and _contains_secret_shape(component)
            else component
            for component in detail["loc"]
        )
        sanitized.append(clean_detail)
    return sanitized


def sanitized_validation_error_json(error: ValidationError) -> str:
    """Serialize validation errors without rejected inputs or context."""
    return json.dumps(sanitized_validation_errors(error), separators=(",", ":"))


class OperationKey(BaseModel):
    """Stable HTTP operation identity for a Platform capability."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True
    )

    method: HttpMethod
    path: str

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, value: object) -> object:
        """Normalize textual methods before validating the closed method set."""
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        """Require an absolute path template without request or location data."""
        _validate_safe_text(value, field_name="path")
        decoded = _decoded_path(value)
        _validate_safe_text(decoded, field_name="decoded path")
        parsed = urlsplit(decoded)
        segments = decoded.replace("\\", "/").split("/")
        if (
            not decoded.startswith("/")
            or decoded.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or "?" in decoded
            or "#" in decoded
            or "\\" in decoded
            or any(segment in {".", ".."} for segment in segments)
        ):
            raise ValueError(
                "path must be an absolute API path without an origin, query, "
                "fragment, traversal, or backslash"
            )
        return decoded


class VerificationState(BaseModel):
    """Evidence flags for one capability.

    ``schema_verified`` uses the public wire alias ``schema`` because Pydantic's
    base class already owns the deprecated ``schema()`` method.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    schema_verified: StrictBool = Field(default=False, alias="schema")
    offline_call: StrictBool = False
    live_call: StrictBool = False


class CapabilityRecord(BaseModel):
    """One declared capability and its current exposure/evidence state."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True
    )

    schema_version: Annotated[StrictInt, Field(ge=1, le=1)] = 1
    id: str
    surface: Surface
    owner_lane: OwnerLane
    source_refs: tuple[str, ...]
    decision_ref: str | None = None
    exclusion_reason: str | None = None
    source_model: str | None = None
    implementation_id: str | None = None
    operation: OperationKey | None = None
    tool_name: str | None = None
    disposition: Disposition
    access_class: AccessClass
    persistence: Persistence
    requirements: tuple[str, ...]
    verification: VerificationState

    @field_validator("id", "tool_name", "implementation_id")
    @classmethod
    def validate_stable_id(cls, value: str | None, info) -> str | None:
        """Validate optional and required stable-token fields."""
        if value is None:
            return value
        if not _STABLE_ID_RE.fullmatch(value) or _contains_secret_shape(value):
            raise ValueError(f"{info.field_name} must be a stable nonempty token")
        return value

    @field_validator("source_refs")
    @classmethod
    def validate_source_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Keep provenance repository-relative and free of local path data."""
        if not values:
            raise ValueError("source_refs must contain at least one provenance reference")
        canonical_values = []
        for value in values:
            _validate_safe_text(value, field_name="source_refs")
            decoded = _decoded_path(value)
            _validate_safe_text(decoded, field_name="decoded source_refs")
            if (
                decoded.startswith(("/", "\\"))
                or re.match(r"^[A-Za-z]:[\\/]", decoded)
                or "://" in decoded
            ):
                raise ValueError(
                    "source_refs must be repository-relative paths or qualified symbols"
                )
            if "\\" in decoded:
                raise ValueError(
                    "source_refs must be repository-relative paths or qualified symbols"
                )
            if decoded.count(":") > 1:
                raise ValueError(
                    "source_refs must contain at most one qualified-symbol separator"
                )
            path_part, separator, symbol = decoded.rpartition(":")
            if not separator:
                path_part = decoded
            elif not path_part:
                raise ValueError("source_refs require a nonempty path or module prefix")
            elif not _QUALIFIED_SYMBOL_RE.fullmatch(symbol):
                raise ValueError("source_refs contain an invalid qualified symbol")
            parsed = urlsplit(path_part)
            decoded_segments = path_part.split("/")
            if (
                parsed.scheme
                or parsed.netloc
                or parsed.query
                or parsed.fragment
                or "?" in decoded
                or "#" in decoded
                or any(segment in {".", ".."} for segment in decoded_segments)
            ):
                raise ValueError(
                    "source_refs must be repository-relative paths or qualified symbols"
                )
            canonical_values.append(decoded)
        return tuple(canonical_values)

    @field_validator("requirements")
    @classmethod
    def validate_requirements(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Accept prerequisite names but reject embedded credential values."""
        return tuple(
            _validate_safe_text(value, field_name="requirements") for value in values
        )

    @field_validator("decision_ref", "exclusion_reason", "source_model")
    @classmethod
    def validate_optional_text(cls, value: str | None, info) -> str | None:
        """Validate optional descriptive metadata when it is supplied."""
        if value is None:
            return None
        return _validate_safe_text(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_exposure_identity(self) -> CapabilityRecord:
        """Require evidence for direct and excluded exposure claims."""
        if self.disposition == "direct":
            if not self.tool_name:
                raise ValueError("direct capabilities require a tool_name")
            if self.surface == "platform" and self.operation is None:
                raise ValueError("direct Platform capabilities require an operation")
        if self.disposition in {"restricted", "unimplemented"} and not (
            self.exclusion_reason or self.decision_ref
        ):
            raise ValueError(
                "restricted and unimplemented capabilities require an exclusion reason "
                "or decision reference"
            )
        return self


class DispositionCounts(BaseModel, Mapping[Disposition, int]):
    """Immutable complete partition of records by exposure disposition."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True
    )

    direct: Annotated[StrictInt, Field(ge=0)] = 0
    workspace_indirect: Annotated[StrictInt, Field(ge=0)] = 0
    metadata_only: Annotated[StrictInt, Field(ge=0)] = 0
    restricted: Annotated[StrictInt, Field(ge=0)] = 0
    unimplemented: Annotated[StrictInt, Field(ge=0)] = 0

    def __getitem__(self, key: Disposition) -> int:
        """Return a disposition count using mapping semantics."""
        if key not in _SUPPORTED_DISPOSITIONS:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self) -> Iterator[Disposition]:
        """Iterate every supported disposition in stable contract order."""
        return iter(_SUPPORTED_DISPOSITIONS)

    def __len__(self) -> int:
        """Return the fixed number of supported disposition categories."""
        return len(_SUPPORTED_DISPOSITIONS)


class CoverageCounts(BaseModel):
    """Explicit gross, approved, and implementation-identity denominators."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True
    )

    gross_records: Annotated[StrictInt, Field(ge=0)]
    approved_records: Annotated[StrictInt, Field(ge=0)]
    unique_implementations: Annotated[StrictInt, Field(ge=0)]
    implementation_aliases: Annotated[StrictInt, Field(ge=0)]
    unidentified_records: Annotated[StrictInt, Field(ge=0)]
    by_disposition: DispositionCounts

    @model_validator(mode="after")
    def validate_denominators(self) -> CoverageCounts:
        """Keep disposition and implementation partitions arithmetically sound."""
        if self.gross_records != sum(self.by_disposition.values()):
            raise ValueError("gross_records must equal the disposition total")
        approved_from_dispositions = sum(
            self.by_disposition[disposition]
            for disposition in _APPROVED_DISPOSITIONS
        )
        if self.approved_records != approved_from_dispositions:
            raise ValueError(
                "approved_records must equal approved disposition counts"
            )
        if self.gross_records != (
            self.unique_implementations
            + self.implementation_aliases
            + self.unidentified_records
        ):
            raise ValueError("gross_records must equal the implementation identity total")
        if self.implementation_aliases and not self.unique_implementations:
            raise ValueError(
                "implementation aliases require at least one unique implementation"
            )
        if self.approved_records > self.gross_records:
            raise ValueError("approved_records cannot exceed gross_records")
        return self


class CapabilityInventory(BaseModel):
    """Versioned set of unique capability records."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True
    )

    schema_version: Annotated[StrictInt, Field(ge=1, le=1)] = 1
    records: tuple[CapabilityRecord, ...]

    @model_validator(mode="after")
    def validate_unique_ids(self) -> CapabilityInventory:
        """Reject duplicate stable IDs while permitting declared aliases."""
        counts = Counter(record.id for record in self.records)
        duplicates = sorted(identifier for identifier, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"Duplicate capability ID: {duplicates[0]}")
        return self

    def coverage_counts(self) -> CoverageCounts:
        """Return denominators without dropping excluded or unidentified work."""
        records = type(self).model_validate(self.model_dump()).records
        identified = [
            (record.surface, record.implementation_id)
            for record in records
            if record.implementation_id is not None
        ]
        unique_implementations = len(set(identified))
        disposition_counts = Counter(record.disposition for record in records)
        return CoverageCounts(
            gross_records=len(records),
            approved_records=sum(
                record.disposition in _APPROVED_DISPOSITIONS for record in records
            ),
            unique_implementations=unique_implementations,
            implementation_aliases=len(identified) - unique_implementations,
            unidentified_records=len(records) - len(identified),
            by_disposition={
                disposition: disposition_counts[disposition]
                for disposition in _SUPPORTED_DISPOSITIONS
            },
        )


__all__ = [
    "AccessClass",
    "CapabilityInventory",
    "CapabilityRecord",
    "CoverageCounts",
    "DispositionCounts",
    "Disposition",
    "HttpMethod",
    "OperationKey",
    "OwnerLane",
    "Persistence",
    "Surface",
    "VerificationState",
    "sanitized_validation_error_json",
    "sanitized_validation_errors",
]
