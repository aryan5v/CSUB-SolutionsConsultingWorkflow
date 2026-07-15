"""Locate and validate against the locked JSON Schemas in packages/contracts.

This dependency-free validator enforces the JSON Schema subset used by the
prototype contracts: local/cross-file references, object and array types,
required/properties, additionalProperties, enum/const, oneOf, lengths, and
numeric bounds. Provider integrations can replace it with a full standards
implementation behind the same ``validate`` entry point if additional keywords
are introduced.
"""

from __future__ import annotations

import datetime
import functools
import json
import math
import os
from pathlib import Path
from urllib.parse import unquote, urlparse


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
    _check(payload, schema, path=schema_name, root_schema=schema)
    return payload


def validate_definition(payload: dict, schema_name: str, definition: str) -> dict:
    """Validate a payload against a named ``$defs`` entry in a contract schema."""
    schema = load_schema(schema_name)
    definitions = schema.get("$defs", {})
    target = definitions.get(definition)
    if not isinstance(target, dict):
        raise ContractValidationError(
            f"{schema_name}: missing schema definition {definition!r}"
        )
    _check(payload, target, path=f"{schema_name}#/$defs/{definition}", root_schema=schema)
    return payload


def _check(value: object, schema: dict, path: str, root_schema: dict) -> None:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        target, target_root = _resolve_reference(reference, root_schema)
        _check(value, target, path, target_root)
        return

    variants = schema.get("oneOf")
    if isinstance(variants, list):
        matches = 0
        for variant in variants:
            try:
                _check(value, variant, path, root_schema)
                matches += 1
            except ContractValidationError:
                pass
        if matches != 1:
            raise ContractValidationError(f"{path}: expected exactly one matching schema, got {matches}")
        return

    if "const" in schema:
        expected_constant = schema["const"]
        if type(value) is not type(expected_constant) or value != expected_constant:
            raise ContractValidationError(f"{path}: expected constant {expected_constant!r}")
    enum = schema.get("enum")
    if enum is not None and value not in enum:
        raise ContractValidationError(f"{path}: {value!r} not in {enum}")

    expected_type = schema.get("type")
    if expected_type is not None and not _matches_type(value, expected_type):
        raise ContractValidationError(f"{path}: value has the wrong type for {expected_type!r}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise ContractValidationError(f"{path}: missing required field '{key}'")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                raise ContractValidationError(f"{path}: unexpected fields {sorted(extras)}")
        for key, item in value.items():
            subschema = properties.get(key)
            if isinstance(subschema, dict):
                _check(item, subschema, f"{path}.{key}", root_schema)

    if isinstance(value, list):
        minimum_items = schema.get("minItems")
        maximum_items = schema.get("maxItems")
        if minimum_items is not None and len(value) < minimum_items:
            raise ContractValidationError(f"{path}: array has fewer than {minimum_items} items")
        if maximum_items is not None and len(value) > maximum_items:
            raise ContractValidationError(f"{path}: array has more than {maximum_items} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _check(item, item_schema, f"{path}[{index}]", root_schema)

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ContractValidationError(f"{path}: string is shorter than {schema['minLength']}")
        value_format = schema.get("format")
        if value_format == "email":
            if len(value) > 254 or value.count("@") != 1:
                raise ContractValidationError(f"{path}: invalid email format")
            if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
                raise ContractValidationError(f"{path}: invalid email format")
            local, domain = value.split("@")
            labels = domain.split(".")
            if (
                not local
                or len(local) > 64
                or local.startswith(".")
                or local.endswith(".")
                or ".." in local
                or len(labels) < 2
                or any(
                    not label
                    or len(label) > 63
                    or label.startswith("-")
                    or label.endswith("-")
                    or not all(char.isalnum() or char == "-" for char in label)
                    for label in labels
                )
            ):
                raise ContractValidationError(f"{path}: invalid email format")
        if value_format == "date-time":
            try:
                parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise ContractValidationError(f"{path}: invalid date-time format") from error
            if parsed.tzinfo is None:
                raise ContractValidationError(f"{path}: date-time must include a timezone")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ContractValidationError(f"{path}: numeric value must be finite")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ContractValidationError(f"{path}: value is below minimum {minimum}")
        if maximum is not None and value > maximum:
            raise ContractValidationError(f"{path}: value is above maximum {maximum}")


def _resolve_reference(reference: str, current_root: dict) -> tuple[dict, dict]:
    document, separator, fragment = reference.partition("#")
    if document:
        filename = Path(urlparse(document).path).name
        suffix = ".schema.json"
        if not filename.endswith(suffix):
            raise ContractValidationError(f"unsupported schema reference: {reference}")
        target_root = load_schema(filename[: -len(suffix)])
    else:
        target_root = current_root
    target: object = target_root
    if separator and fragment:
        for raw_part in fragment.lstrip("/").split("/"):
            part = unquote(raw_part).replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                raise ContractValidationError(f"unresolved schema reference: {reference}")
            target = target[part]
    if not isinstance(target, dict):
        raise ContractValidationError(f"schema reference is not an object: {reference}")
    return target, target_root


def _matches_type(value: object, expected: object) -> bool:
    if isinstance(expected, list):
        return any(_matches_type(value, item) for item in expected)
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    check = checks.get(expected)
    return False if check is None else check(value)
