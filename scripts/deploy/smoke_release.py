#!/usr/bin/env python3
"""Post-deploy VETTED canary with public and IAM-authenticated probes."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


def retry(label: str, operation: Callable[[], None], attempts: int, delay: float) -> None:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            operation()
            print(f"PASS {label}")
            return
        except Exception as error:  # noqa: BLE001 - bounded canary retry
            last_error = error
            if attempt < attempts:
                print(f"RETRY {label} ({attempt}/{attempts}): {error}")
                time.sleep(delay)
    raise RuntimeError(f"FAIL {label}: {last_error}") from last_error


def request(
    url: str, *, method: str = "GET", headers: dict[str, str] | None = None
) -> tuple[int, bytes, dict[str, str]]:
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "User-Agent": "vetted-release-canary/1.0",
            "Cache-Control": "no-cache",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read(), {
                key.lower(): value for key, value in response.headers.items()
            }
    except urllib.error.HTTPError as error:
        return error.code, error.read(), {
            key.lower(): value for key, value in error.headers.items()
        }


def api_event(path: str, *, query: str = "") -> dict[str, Any]:
    return {
        "version": "2.0",
        "routeKey": f"GET {path}",
        "rawPath": path,
        "rawQueryString": query,
        "headers": {},
        "requestContext": {
            "http": {"method": "GET", "path": path},
            "authorizer": {
                "jwt": {
                    "claims": {
                        "email": "cd-canary@vetted.invalid",
                        "custom:workspace_id": "csub-demo",
                    }
                }
            },
        },
        "isBase64Encoded": False,
    }


def invoke_lambda(function_name: str, event: dict[str, Any], region: str) -> Any:
    with tempfile.TemporaryDirectory() as directory:
        payload = Path(directory, "event.json")
        response = Path(directory, "response.json")
        payload.write_text(json.dumps(event), encoding="utf-8")
        command = [
            "aws",
            "lambda",
            "invoke",
            "--function-name",
            function_name,
            "--region",
            region,
            "--cli-binary-format",
            "raw-in-base64-out",
            "--payload",
            f"fileb://{payload}",
            str(response),
        ]
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            error = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown AWS CLI error"
            raise RuntimeError(f"Lambda invoke failed: {error}")
        metadata = json.loads(result.stdout)
        if metadata.get("FunctionError"):
            raise RuntimeError("Lambda reported FunctionError")
        envelope = json.loads(response.read_text(encoding="utf-8"))
        if envelope.get("statusCode") != 200:
            raise RuntimeError(f"Lambda API returned {envelope.get('statusCode')}")
        return json.loads(envelope.get("body") or "null")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cloudfront-domain", required=True)
    parser.add_argument("--api-endpoint", required=True)
    parser.add_argument("--cognito-client-id", required=True)
    parser.add_argument("--lambda-name", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-catalog-rows", type=int, default=982)
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--delay-seconds", type=float, default=10)
    args = parser.parse_args(argv)

    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha):
        raise SystemExit("--expected-sha must be a full commit SHA")
    region = os.environ.get("AWS_REGION", "us-west-2")
    site = f"https://{args.cloudfront_domain}"
    api = args.api_endpoint.rstrip("/")

    def frontend() -> None:
        status, body, _ = request(f"{site}/login")
        if status != 200 or b"<title>Vetted</title>" not in body:
            raise RuntimeError(f"login shell returned status={status}")

    def release_manifest() -> None:
        status, body, headers = request(f"{site}/release.json?sha={args.expected_sha}")
        if status != 200 or "json" not in headers.get("content-type", ""):
            raise RuntimeError(f"release manifest returned status={status}")
        value = json.loads(body)
        if value.get("sha") != args.expected_sha:
            raise RuntimeError(f"expected {args.expected_sha}, got {value.get('sha')}")

    def auth_session() -> None:
        status, body, headers = request(f"{site}/api/auth/get-session")
        if status != 200:
            raise RuntimeError(f"auth session returned status={status}")
        if json.loads(body) not in (None, {}):
            raise RuntimeError("anonymous auth probe unexpectedly returned a session")
        if "no-store" not in headers.get("cache-control", ""):
            raise RuntimeError("anonymous auth response is cacheable")

    def health() -> None:
        status, body, _ = request(f"{api}/health")
        value = json.loads(body)
        if status != 200 or value.get("status") != "ok" or value.get("live") is not True:
            raise RuntimeError(f"health returned status={status}, payload={value}")

    def queue() -> None:
        value = invoke_lambda(args.lambda_name, api_event("/review-queue"), region)
        if not isinstance(value.get("items"), list) or not value["items"]:
            raise RuntimeError("review queue did not return seeded items")

    def catalog() -> None:
        value = invoke_lambda(
            args.lambda_name,
            api_event("/catalog", query="limit=1&offset=0"),
            region,
        )
        if value.get("total") != args.expected_catalog_rows:
            raise RuntimeError(
                f"expected {args.expected_catalog_rows} catalog rows, got {value.get('total')}"
            )
        if value.get("catalog_membership_is_approval") is not False:
            raise RuntimeError("catalog response lost its non-approval boundary")

    def frontend_configuration() -> None:
        _, index, _ = request(f"{site}/")
        marker = b'type="module" crossorigin src="'
        if marker not in index:
            raise RuntimeError("frontend module asset was not found")
        asset = index.split(marker, 1)[1].split(b'"', 1)[0].decode("utf-8")
        status, javascript, headers = request(f"{site}{asset}")
        if status != 200 or "javascript" not in headers.get("content-type", ""):
            raise RuntimeError(f"frontend asset returned status={status}")
        required = (args.api_endpoint.encode(), args.cognito_client_id.encode())
        if any(value not in javascript for value in required):
            raise RuntimeError("frontend asset is not wired to the deployed API and Cognito client")

    def intake_shell() -> None:
        status, body, _ = request(f"{site}/intake")
        if status != 200 or b"<title>Vetted</title>" not in body:
            raise RuntimeError(f"intake shell returned status={status}")

    def cors() -> None:
        status, _, headers = request(
            f"{api}/health",
            method="OPTIONS",
            headers={
                "Origin": site,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        if status not in (200, 204) or headers.get("access-control-allow-origin") != site:
            raise RuntimeError(f"allowlisted browser CORS failed with status={status}")

    for label, probe in (
        ("frontend shell", frontend),
        ("vendor intake shell", intake_shell),
        ("release manifest", release_manifest),
        ("frontend live configuration", frontend_configuration),
        ("Better Auth session endpoint", auth_session),
        ("public API health", health),
        ("browser-origin API CORS", cors),
        ("seeded review queue", queue),
        ("982-row software catalog", catalog),
    ):
        retry(label, probe, args.attempts, args.delay_seconds)

    print(f"VETTED release {args.expected_sha} passed every canary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
