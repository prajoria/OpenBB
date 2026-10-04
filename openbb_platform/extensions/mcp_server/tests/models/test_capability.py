"""Capability metadata contract and immutable baseline tests."""

import csv
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import get_args

import pytest
from openbb_mcp_server.models import capability as module
from pydantic import ValidationError

FIXTURES = Path(__file__).parents[1] / "fixtures"
AUDIT_SOURCE_COMMIT = "39f171603c9bc4a28778e668ba981cf0e4358b9a"
AUDIT_MANIFEST_SHA256 = (
    "ed1a583f307ca22117da6d079bfdc6a9768c6697c39da1d91e49b18f5c5e92fa"
)


def repository_normalized_bytes(path: Path) -> bytes:
    """Return text bytes as Git stores them under the repository LF policy."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def record_data() -> dict:
    """Return an independent copy of the synthetic provider-read record."""
    return json.loads(
        (FIXTURES / "capability_inventory.json").read_text(encoding="utf-8")
    )["records"][0]


def test_round_trip_preserves_false_flags_and_public_alias():
    """The wire schema flag survives nested round trips without framework shadowing."""
    inventory = module.CapabilityInventory.model_validate_json(
        (FIXTURES / "capability_inventory.json").read_text(encoding="utf-8")
    )
    restored = module.CapabilityInventory.model_validate_json(
        inventory.model_dump_json()
    )
    assert restored == inventory
    assert restored.records[0].verification.schema_verified is True
    assert restored.model_dump()["records"][0]["verification"]["schema"] is True
    assert restored.model_dump()["records"][1]["verification"] == {
        "schema": False,
        "offline_call": False,
        "live_call": False,
    }
    assert "schema" in module.VerificationState.model_json_schema()["properties"]
    assert (
        "schema_verified"
        not in module.VerificationState.model_json_schema()["properties"]
    )


def test_private_verification_name_is_not_a_wire_alias():
    """Wire inputs accept only the documented ``schema`` spelling."""
    with pytest.raises(ValidationError, match="only supported wire field"):
        module.VerificationState.model_validate_json('{"schema_verified": true}')


@pytest.mark.parametrize("model", ["record", "operation", "verification", "inventory"])
def test_unknown_fields_are_rejected(model):
    """Every contract layer rejects fields outside its published schema."""
    cases = {
        "record": (module.CapabilityRecord, record_data()),
        "operation": (
            module.OperationKey,
            {"method": "GET", "path": "/api/v1/synthetic"},
        ),
        "verification": (module.VerificationState, {}),
        "inventory": (module.CapabilityInventory, {"records": []}),
    }
    cls, payload = cases[model]
    payload["unexpected"] = "not-supported"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        cls.model_validate(payload)


@pytest.mark.parametrize("value", ["false", 0, 1, None])
def test_verification_flags_do_not_coerce_truthiness(value):
    """Unverified does not turn into verified through input coercion."""
    with pytest.raises(ValidationError):
        module.VerificationState.model_validate({"schema": value})


@pytest.mark.parametrize("version", [True, "1", 2])
def test_schema_version_is_an_exact_supported_integer(version):
    """Boolean equality and strings cannot impersonate the schema version."""
    with pytest.raises(ValidationError):
        module.CapabilityRecord.model_validate(
            {**record_data(), "schema_version": version}
        )


@pytest.mark.parametrize("identifier", ["", " ", "bad id", "id\nsuffix"])
def test_invalid_capability_identity_is_rejected(identifier):
    """Stable identities are nonempty single tokens."""
    with pytest.raises(ValidationError):
        module.CapabilityRecord.model_validate({**record_data(), "id": identifier})


def test_operation_normalizes_method_and_is_frozen():
    """An operation has normalized immutable HTTP identity."""
    operation = module.OperationKey(method=" get ", path="/api/v1/synthetic/{symbol}")
    assert operation.method == "GET"
    with pytest.raises(ValidationError, match="frozen_instance"):
        operation.method = "POST"


@pytest.mark.parametrize(
    "path",
    [
        "api/v1/synthetic",
        "https://example.invalid/api",
        "//example.invalid/api",
        "/api?token=value",
        "/api#fragment",
        "/api/../private",
        "/api/%2e%2e/private",
        "/api%3Ftoken=value",
        "/api%23fragment",
        "/api\\private",
        "/api\n/private",
        "/api/%0a/private",
        "/api/%250a/private",
        "/api/%00/private",
        "/%2fexample.invalid/api",
        "/%25252e%25252e/private",
        "/%25250a/private",
        "/api/%FF",
        "/api/%FE",
        "/api/%C0",
        "/api/%25FF",
        "/api/%ZZ",
        "/api/%",
        "/api/%2525252e",
        "/api/%252525ZZ",
        "/api/%252525",
        "/api/\u0085private",
        "/api/\u2028private",
    ],
)
def test_operation_rejects_noncanonical_paths(path):
    """Only absolute path templates, never locations or request data, are accepted."""
    with pytest.raises(ValidationError):
        module.OperationKey(method="GET", path=path)


@pytest.mark.parametrize(
    "source",
    [
        "/private/source.py",
        "../private.py",
        "src/../private.py",
        "C:\\private\\source.py",
        "\\\\host\\private.py",
        "https://example.invalid/source.py",
        "src/file.py:../../private.py",
        "module:../secret",
        "a.py:%2e%2e/secret",
        ":Symbol",
        "src/file.py?rev=1",
        "src/file.py#fragment",
        "%2Fprivate/source.py",
        "https%3A%2F%2Fexample.invalid/source.py",
        "C%3A/private/source.py",
        "C:private.py",
        "C%3Aprivate.py",
        "~/.ssh/id_rsa",
        "~user/private.py",
        "src/..:Symbol",
        "src/.:Symbol",
        "src/%2e%2e:Symbol",
        "%FF.py",
        "%25FF.py",
        "%ZZ.py",
        "%.py",
        "%2525252e.py",
        "%252525ZZ.py",
        "%252525.py",
    ],
)
def test_source_references_cannot_be_machine_paths(source):
    """Committed provenance cannot carry absolute machine locations."""
    with pytest.raises(ValidationError):
        module.CapabilityRecord.model_validate(
            {**record_data(), "source_refs": [source]}
        )


def test_source_references_accept_qualified_symbols():
    """A module-qualified symbol is valid provenance without a filesystem path."""
    record = module.CapabilityRecord.model_validate(
        {**record_data(), "source_refs": ["package.module:SyntheticQuoteFetcher"]}
    )
    assert record.source_refs == ("package.module:SyntheticQuoteFetcher",)


def test_operation_and_source_references_use_canonical_values():
    """Equivalent encoded metadata has one stable identity."""
    operation = module.OperationKey(method="GET", path="/api/%73ynthetic")
    record = module.CapabilityRecord.model_validate(
        {**record_data(), "source_refs": ["package%2Emodule:SyntheticQuoteFetcher"]}
    )
    assert operation.path == "/api/synthetic"
    assert record.source_refs == ("package.module:SyntheticQuoteFetcher",)


@pytest.mark.parametrize("field", ["id", "tool_name", "implementation_id"])
def test_credential_shaped_stable_identifiers_are_rejected(field):
    """Stable identifiers cannot carry recognizable credential assignments."""
    with pytest.raises(ValidationError):
        module.CapabilityRecord.model_validate(
            {**record_data(), field: "api_key:synthetic-value"}
        )


def test_rejected_credential_values_are_hidden_from_validation_errors():
    """Published error forms do not echo rejected credential material."""
    rejected_value = "api_key=DO_NOT_LOG_THIS_VALUE"
    with pytest.raises(ValidationError) as captured:
        module.CapabilityRecord.model_validate(
            {**record_data(), "requirements": [rejected_value]}
        )
    assert rejected_value not in str(captured.value)
    assert rejected_value not in json.dumps(
        module.sanitized_validation_errors(captured.value)
    )
    assert rejected_value not in module.sanitized_validation_error_json(captured.value)
    assert all(
        "input" not in detail
        for detail in module.sanitized_validation_errors(captured.value)
    )


@pytest.mark.parametrize(
    "rejected_key",
    [
        "api_key=DO_NOT_LOG_THIS_FIELD",
        "FMP_SECRET_KEY=DO_NOT_LOG_THIS_FIELD",
        "PRIVATE_KEY=DO_NOT_LOG_THIS_FIELD",
        '"FMP_SECRET_KEY": "DO_NOT_LOG_THIS_FIELD"',
        "'PRIVATE_KEY': 'DO_NOT_LOG_THIS_FIELD'",
        "sk-live-DO_NOT_LOG_THIS_FIELD",
    ],
)
def test_rejected_credential_field_name_is_hidden_from_published_errors(
    rejected_key,
):
    """An extra-field location cannot smuggle credential material into logs."""
    with pytest.raises(ValidationError) as captured:
        module.CapabilityInventory.model_validate(
            {"records": [], rejected_key: "rejected"}
        )
    details = module.sanitized_validation_errors(captured.value)
    serialized = module.sanitized_validation_error_json(captured.value)
    assert rejected_key not in json.dumps(details)
    assert rejected_key not in serialized
    assert details[0]["loc"] == ("<rejected-field>",)


def test_url_parser_errors_do_not_publish_rejected_path_contents():
    """Parser diagnostics are replaced before validation errors are published."""
    rejected_path = "//DO_NOT_LOG_THIS\uff0fapi"
    with pytest.raises(ValidationError) as captured:
        module.OperationKey(method="GET", path=rejected_path)
    assert "DO_NOT_LOG_THIS" not in module.sanitized_validation_error_json(
        captured.value
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"tool_name": None},
        {"operation": None},
        {"source_refs": []},
        {"tool_name": ""},
        {"implementation_id": ""},
    ],
)
def test_direct_platform_records_require_complete_identity(changes):
    """A direct claim needs a valid Platform operation and named tool."""
    with pytest.raises(ValidationError):
        module.CapabilityRecord.model_validate({**record_data(), **changes})


@pytest.mark.parametrize("surface", ["workspace", "agents", "daytrade"])
def test_explicit_specialist_tool_does_not_require_http_route(surface):
    """Explicit MCP registries are not forced into an invented HTTP operation."""
    record = module.CapabilityRecord.model_validate(
        {**record_data(), "surface": surface, "operation": None}
    )
    assert record.tool_name == "synthetic_quote"
    assert record.operation is None


@pytest.mark.parametrize("disposition", ["restricted", "unimplemented"])
def test_excluded_records_need_a_reason(disposition):
    """Coverage cannot silently remove restricted or missing work."""
    with pytest.raises(ValidationError, match="reason"):
        module.CapabilityRecord.model_validate(
            {**record_data(), "disposition": disposition, "exclusion_reason": None}
        )


@pytest.mark.parametrize(
    "text",
    [
        "api_key=synthetic-value",
        "FMP_API_KEY=synthetic-value",
        "api_key%3Dsynthetic-value",
        "api_key%253Dsynthetic-value",
        "%FF api_key%3Dsynthetic-value",
        "%FF api_key%253Dsynthetic-value",
        "MY_ACCESS_TOKEN=synthetic-value",
        "FMP_SECRET_KEY=synthetic-value",
        "PRIVATE_KEY=synthetic-value",
        '"FMP_SECRET_KEY": "synthetic-value"',
        "'PRIVATE_KEY': 'synthetic-value'",
        "PASSWORD: synthetic-value",
        "Authorization: Bearer synthetic-value",
        "Authorization: Basic synthetic-value",
        "https://synthetic-user:synthetic-password@example.invalid",
        "-----BEGIN PRIVATE KEY-----",
    ],
)
@pytest.mark.parametrize("field", ["requirements", "source_refs", "exclusion_reason"])
def test_credential_shaped_metadata_is_rejected(field, text):
    """Prerequisite names are allowed; recognizable credential values are not."""
    value = [text] if field in {"requirements", "source_refs"} else text
    with pytest.raises(ValidationError):
        module.CapabilityRecord.model_validate({**record_data(), field: value})


@pytest.mark.parametrize("text", ["line\u0085break", "line\u2028break"])
@pytest.mark.parametrize("field", ["requirements", "source_refs", "exclusion_reason"])
def test_non_printable_metadata_is_rejected(field, text):
    """Unicode control and line-separator characters cannot enter metadata."""
    value = [text] if field in {"requirements", "source_refs"} else text
    with pytest.raises(ValidationError):
        module.CapabilityRecord.model_validate({**record_data(), field: value})


def test_counts_preserve_gross_coverage_and_identified_aliases():
    """Restricted work and aliases cannot inflate the success denominator."""
    inventory = module.CapabilityInventory.model_validate_json(
        (FIXTURES / "capability_inventory.json").read_text(encoding="utf-8")
    )
    counts = inventory.coverage_counts()
    assert counts.gross_records == 9
    assert counts.approved_records == 5
    assert counts.unique_implementations == 7
    assert counts.implementation_aliases == 1
    assert counts.unidentified_records == 1
    assert counts.by_disposition.model_dump() == {
        "direct": 3,
        "workspace_indirect": 1,
        "metadata_only": 1,
        "restricted": 3,
        "unimplemented": 1,
    }
    assert len({record.access_class for record in inventory.records}) == 8


def test_duplicate_record_ids_are_rejected():
    """An alias needs its own stable ID even when its implementation is shared."""
    record = record_data()
    with pytest.raises(ValidationError, match="must be unique"):
        module.CapabilityInventory.model_validate(
            {"records": [record, deepcopy(record)]}
        )


def test_duplicate_id_error_does_not_publish_identifier_contents():
    """Sanitized duplicate errors never interpolate an untrusted identifier."""
    sensitive_id = "eyJhbGciOiJIUzI1NiJ9.synthetic.signature"
    record = {**record_data(), "id": sensitive_id}
    with pytest.raises(ValidationError) as captured:
        module.CapabilityInventory.model_validate(
            {"records": [record, deepcopy(record)]}
        )
    assert sensitive_id not in json.dumps(
        module.sanitized_validation_errors(captured.value)
    )
    assert sensitive_id not in module.sanitized_validation_error_json(captured.value)


def test_empty_inventory_has_explicit_zero_denominators():
    """No records is zero coverage, not implicit complete coverage."""
    counts = module.CapabilityInventory(records=[]).coverage_counts()
    assert counts.gross_records == counts.approved_records == 0
    assert counts.unique_implementations == counts.implementation_aliases == 0
    assert counts.unidentified_records == 0
    assert set(counts.by_disposition.values()) == {0}
    assert set(counts.by_disposition.model_fields) == set(get_args(module.Disposition))


def test_assignment_revalidates_records_and_evidence():
    """Contract objects reject assignment and retain their original values."""
    record = module.CapabilityRecord.model_validate(record_data())
    with pytest.raises(ValidationError):
        record.verification.live_call = 1
    with pytest.raises(ValidationError):
        record.disposition = "unknown"
    with pytest.raises(ValidationError):
        record.tool_name = None
    assert record.verification.live_call is False
    assert record.disposition == "direct"
    assert record.tool_name == "synthetic_quote"


def test_inventory_and_nested_sequences_are_immutable():
    """Container mutation cannot invalidate a previously validated inventory."""
    inventory = module.CapabilityInventory.model_validate({"records": [record_data()]})
    with pytest.raises(ValidationError):
        inventory.records += (inventory.records[0],)
    with pytest.raises(AttributeError):
        inventory.records[0].source_refs.append("../private.py")
    assert inventory.coverage_counts().gross_records == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"gross_records": -1},
        {"approved_records": 10},
        {"approved_records": 0},
        {
            "unique_implementations": 0,
            "implementation_aliases": 1,
            "unidentified_records": 0,
        },
        {
            "by_disposition": {
                "direct": 0,
                "workspace_indirect": 0,
                "metadata_only": 0,
                "restricted": 0,
                "unimplemented": 0,
            }
        },
    ],
)
def test_coverage_counts_reject_impossible_denominators(changes):
    """Published counts cannot be negative or violate their partitions."""
    valid = {
        "gross_records": 1,
        "approved_records": 1,
        "unique_implementations": 1,
        "implementation_aliases": 0,
        "unidentified_records": 0,
        "by_disposition": {
            "direct": 1,
            "workspace_indirect": 0,
            "metadata_only": 0,
            "restricted": 0,
            "unimplemented": 0,
        },
    }
    with pytest.raises(ValidationError):
        module.CoverageCounts.model_validate({**valid, **changes})


def test_disposition_counts_are_deeply_immutable():
    """Frozen coverage results do not expose a mutable count dictionary."""
    counts = module.CapabilityInventory.model_validate(
        {"records": [record_data()]}
    ).coverage_counts()
    with pytest.raises(ValidationError):
        counts.by_disposition.direct = 99
    assert counts.gross_records == sum(counts.by_disposition.values()) == 1


def test_implementation_identity_is_qualified_by_surface():
    """Coincidentally equal specialist names do not become one implementation."""
    record = record_data()
    other = {**record, "id": "agents:quote", "surface": "agents", "operation": None}
    counts = module.CapabilityInventory.model_validate(
        {"records": [record, other]}
    ).coverage_counts()
    assert counts.unique_implementations == 2
    assert counts.implementation_aliases == 0


def test_historical_audit_artifacts_are_immutable():
    """Byte-level provenance and historical gross counts remain traceable."""
    root = FIXTURES / "capability_audit"
    assert (
        hashlib.sha256(repository_normalized_bytes(root / "manifest.json")).hexdigest()
        == AUDIT_MANIFEST_SHA256
    )
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_commit"] == AUDIT_SOURCE_COMMIT
    for name, digest in manifest["sha256"].items():
        assert (
            hashlib.sha256(repository_normalized_bytes(root / name)).hexdigest()
            == digest
        )
    tables = {}
    for name in [
        "mcp-api-inventory.csv",
        "mcp-fmp-model-coverage.csv",
        "portfolio-recent-commits.csv",
    ]:
        with (root / name).open(encoding="utf-8", newline="") as stream:
            tables[name] = list(csv.DictReader(stream))
    assert len(tables["mcp-api-inventory.csv"]) == manifest["counts"]["api_rows"] == 317
    fmp = tables["mcp-fmp-model-coverage.csv"]
    assert len(fmp) == manifest["counts"]["fmp_models"] == 181
    assert (
        sum(int(row["registered_command_count"]) > 0 for row in fmp)
        == manifest["counts"]["fmp_routed_models"]
        == 70
    )
    assert (
        sum(int(row["registered_command_count"]) == 0 for row in fmp)
        == manifest["counts"]["fmp_unrouted_models"]
        == 111
    )
    assert (
        len(tables["portfolio-recent-commits.csv"])
        == manifest["counts"]["recent_commits"]
        == 948
    )
    snapshot = json.loads(
        (root / "mcp-catalog-snapshot.json").read_text(encoding="utf-8")
    )
    assert snapshot["parent_commit"] == AUDIT_SOURCE_COMMIT
