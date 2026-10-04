"""Validated metadata contracts for MCP capability inventories."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Annotated, Any, Literal, get_args
from urllib.parse import SplitResult, unquote, urlsplit

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
_APPROVED_DISPOSITIONS: frozenset[Disposition] = frozenset(
    {"direct", "workspace_indirect", "metadata_only"}
)
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_QUALIFIED_SYMBOL_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
)
_INVALID_PERCENT_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_PERCENT_ESCAPE_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_MAX_PERCENT_ENCODING_DEPTH = 3
_SECRET_PATTERNS = (
    re.compile(
        r"""(?ix)["']?(?:api[_-]?key|secret[_-]?key|private[_-]?key|password|"""
        r"""passwd|secret|access[_-]?token|token)["']?\s*[:=]\s*["']?\S+"""
    ),
    re.compile(r"(?i)\bauthorization\s*:\s*(?:bearer|basic)\s+\S+"),
    re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)[a-z][a-z0-9+.-]*://[^/@:\s]+:[^/@\s]+@"),
)


def _contains_secret_shape(value: str) -> bool:
    """Return whether *value* resembles credential material."""
    if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
        return True
    decoded = value
    for _ in range(_MAX_PERCENT_ENCODING_DEPTH):
        candidate = unquote(decoded, errors="replace")
        if candidate == decoded:
            return False
        if any(pattern.search(candidate) for pattern in _SECRET_PATTERNS):
            return True
        decoded = candidate
    return bool(_PERCENT_ESCAPE_RE.search(decoded))


def _validate_safe_text(value: str, *, field_name: str) -> str:
    """Validate nonempty metadata text without leaking its content in errors."""
    if not value or value != value.strip():
        raise ValueError(f"{field_name} entries must be nonempty and trimmed")
    if not value.isprintable():
        raise ValueError(
            f"{field_name} entries cannot contain control or non-printable characters"
        )
    if _contains_secret_shape(value):
        raise ValueError(
            f"{field_name} entries cannot contain credential-shaped values"
        )
    return value


def _decoded_path(value: str) -> str:
    """Decode nested percent encoding to a stable canonical value."""
    decoded = value
    for _ in range(_MAX_PERCENT_ENCODING_DEPTH):
        if _INVALID_PERCENT_ESCAPE_RE.search(decoded):
            raise ValueError("percent encoding must use complete hexadecimal escapes")
        try:
            candidate = unquote(decoded, errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("percent encoding must contain valid UTF-8") from error
        if candidate == decoded:
            return decoded
        decoded = candidate
    if _INVALID_PERCENT_ESCAPE_RE.search(decoded):
        raise ValueError("percent encoding must use complete hexadecimal escapes")
    if _PERCENT_ESCAPE_RE.search(decoded):
        raise ValueError("percent encoding exceeds the supported nesting depth")
    return decoded


def _safe_urlsplit(value: str) -> SplitResult:
    """Split URL-like metadata without propagating parser input in errors."""
    try:
        return urlsplit(value)
    except ValueError:
        raise ValueError("path contains invalid URL syntax") from None


def sanitized_validation_errors(error: ValidationError) -> list[dict[str, Any]]:
    """Return structured validation errors without rejected inputs or context."""
    sanitized = []
    for detail in error.errors(include_input=False, include_context=False):
        clean_detail = dict(detail)
        location = list(detail["loc"])
        if detail["type"] == "extra_forbidden" and location:
            location[-1] = "<rejected-field>"
        else:
            location = [
                (
                    "<rejected-field>"
                    if isinstance(component, str) and _contains_secret_shape(component)
                    else component
                )
                for component in location
            ]
        clean_detail["loc"] = tuple(location)
        sanitized.append(clean_detail)
    return sanitized


def sanitized_validation_error_json(error: ValidationError) -> str:
    """Serialize validation errors without rejected inputs or context."""
    return json.dumps(sanitized_validation_errors(error), separators=(",", ":"))


class OperationKey(BaseModel):
    """Stable HTTP operation identity for a Platform capability."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

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
        parsed = _safe_urlsplit(decoded)
        if not decoded.startswith("/") or decoded.startswith("//"):
            raise ValueError("path must be one absolute API path")
        segments = decoded.replace("\\", "/").split("/")
        invalid_path = (
            bool(parsed.scheme),
            bool(parsed.netloc),
            bool(parsed.query),
            bool(parsed.fragment),
            "?" in decoded,
            "#" in decoded,
            "\\" in decoded,
            any(segment in {".", ".."} for segment in segments),
        )
        if any(invalid_path):
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
        validate_by_name=False,
        serialize_by_alias=True,
    )

    schema_verified: StrictBool = Field(default=False, alias="schema")
    offline_call: StrictBool = False
    live_call: StrictBool = False

    @model_validator(mode="before")
    @classmethod
    def reject_private_wire_name(cls, value: Any) -> Any:
        """Require the public ``schema`` alias in wire mappings."""
        if isinstance(value, dict) and "schema_verified" in value:
            raise ValueError("schema is the only supported wire field name")
        return value


class CapabilityRecord(BaseModel):
    """One declared capability and its current exposure/evidence state."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

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
            raise ValueError(
                "source_refs must contain at least one provenance reference"
            )
        canonical_values = []
        for value in values:
            _validate_safe_text(value, field_name="source_refs")
            decoded = _decoded_path(value)
            _validate_safe_text(decoded, field_name="decoded source_refs")
            if (
                decoded.startswith(("/", "\\", "~"))
                or re.match(r"^[A-Za-z]:", decoded)
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
            parsed = _safe_urlsplit(path_part)
            decoded_segments = path_part.split("/")
            invalid_reference = (
                bool(parsed.scheme),
                bool(parsed.netloc),
                bool(parsed.query),
                bool(parsed.fragment),
                "?" in decoded,
                "#" in decoded,
                any(segment in {".", ".."} for segment in decoded_segments),
            )
            if any(invalid_reference):
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


class DispositionCounts(BaseModel):
    """Immutable complete partition of records by exposure disposition."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

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

    def values(self) -> tuple[int, ...]:
        """Return counts in stable contract order."""
        return tuple(self[disposition] for disposition in _SUPPORTED_DISPOSITIONS)


class CoverageCounts(BaseModel):
    """Explicit gross, approved, and implementation-identity denominators."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

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
            self.by_disposition[disposition] for disposition in _APPROVED_DISPOSITIONS
        )
        if self.approved_records != approved_from_dispositions:
            raise ValueError("approved_records must equal approved disposition counts")
        if self.gross_records != (
            self.unique_implementations
            + self.implementation_aliases
            + self.unidentified_records
        ):
            raise ValueError(
                "gross_records must equal the implementation identity total"
            )
        if self.implementation_aliases and not self.unique_implementations:
            raise ValueError(
                "implementation aliases require at least one unique implementation"
            )
        if self.approved_records > self.gross_records:
            raise ValueError("approved_records cannot exceed gross_records")
        return self


class CapabilityInventory(BaseModel):
    """Versioned set of unique capability records."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Annotated[StrictInt, Field(ge=1, le=1)] = 1
    records: tuple[CapabilityRecord, ...]

    @model_validator(mode="after")
    def validate_unique_ids(self) -> CapabilityInventory:
        """Reject duplicate stable IDs while permitting declared aliases."""
        counts = Counter(record.id for record in self.records)
        duplicates = sorted(
            identifier for identifier, count in counts.items() if count > 1
        )
        if duplicates:
            raise ValueError("Capability IDs must be unique")
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
            by_disposition=DispositionCounts.model_validate(
                {
                    disposition: disposition_counts[disposition]
                    for disposition in _SUPPORTED_DISPOSITIONS
                }
            ),
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
