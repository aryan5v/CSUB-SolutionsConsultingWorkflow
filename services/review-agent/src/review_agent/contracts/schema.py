"""Locate and validate against the locked JSON Schemas in packages/contracts.

This is a lightweight boundary validator, not a full JSON Schema engine. It
checks ``required`` keys and top-level ``enum`` constraints, which is enough to
catch contract drift in the Tuesday local slice. Wednesday can swap in a full
validator (e.g. ``jsonschema``) behind the same ``validate`` entry point.
"""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path


class ContractValidationError(ValueError):
    """Raised when a payload violates its locked contract."""


def _find_contracts_dir() -> Path:
    """Resolve packages/contracts/schemas by env override or by walking up."""
    override = os.environ.get("CONTRACTS_SCHEMA_DIR")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "packages" / "contracts" / "schemas"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "Could not locate packages/contracts/schemas; set CONTRACTS_SCHEMA_DIR."
    )


@functools.lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    """Load a schema by file stem, e.g. ``case-intake`` or ``policy-result``."""
    path = _find_contracts_dir() / f"{name}.schema.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate(payload: dict, schema_name: str) -> dict:
    """Validate ``payload`` against a named schema. Returns it unchanged on success."""
    schema = load_schema(schema_name)
    _check(payload, schema, path=schema_name)
    return payload


def _check(value: object, schema: dict, path: str) -> None:
    required = schema.get("required", [])
    if isinstance(value, dict):
        for key in required:
            if key not in value:
                raise ContractValidationError(f"{path}: missing required field '{key}'")
        props = schema.get("properties", {})
        for key, subschema in props.items():
            if key in value and isinstance(subschema, dict):
                enum = subschema.get("enum")
                if enum is not None and value[key] not in enum:
                    raise ContractValidationError(
                        f"{path}.{key}: '{value[key]}' not in {enum}"
                    )
