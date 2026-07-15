"""Post-deploy canary for the disposable vendor invitation handoff.

Set VETTED_API_BASE_URL and VETTED_REVIEWER_TOKEN, then run this script against
an approved sanitized demo deployment. The opaque invitation token is held only
in memory, sent only as a bearer credential, and never printed.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any


class CanaryFailure(RuntimeError):
    pass


def request_json(
    base_url: str,
    reviewer_token: str,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    vendor_token: str | None = None,
    expected_status: int,
) -> dict[str, Any]:
    correlation_id = f"invite-canary-{uuid.uuid4()}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Correlation-Id": correlation_id,
    }
    headers["Authorization"] = f"Bearer {vendor_token or reviewer_token}"
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(body or {}).encode("utf-8") if method != "GET" else None,
        headers=headers,
        method=method,
    )
    try:
        response = urllib.request.urlopen(request, timeout=20)
        status = response.status
        payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        status = error.code
        payload = json.loads(error.read().decode("utf-8"))
    if status != expected_status:
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = error.get("code", "unexpected_response")
        reference = error.get("correlation_id", correlation_id)
        raise CanaryFailure(f"{method} {path} returned {status} ({code}); reference {reference}")
    if not isinstance(payload, dict):
        raise CanaryFailure(f"{method} {path} returned a malformed payload; reference {correlation_id}")
    return payload


def run() -> dict[str, str]:
    base_url = os.environ.get("VETTED_API_BASE_URL", "").rstrip("/")
    reviewer_token = os.environ.get("VETTED_REVIEWER_TOKEN", "").strip()
    if not base_url.startswith("https://"):
        raise CanaryFailure("VETTED_API_BASE_URL must be an HTTPS API base URL")
    if not reviewer_token:
        raise CanaryFailure("VETTED_REVIEWER_TOKEN is required")

    suffix = uuid.uuid4().hex[:10]
    vendor = request_json(
        base_url,
        reviewer_token,
        "POST",
        "/vendors",
        body={"name": f"Invitation Canary Vendor {suffix}", "official_domain": "example.edu"},
        expected_status=201,
    )
    product = request_json(
        base_url,
        reviewer_token,
        "POST",
        "/vendor-products",
        body={"vendor_id": vendor["vendor_id"], "name": f"Invitation Canary Product {suffix}"},
        expected_status=201,
    )
    contact = request_json(
        base_url,
        reviewer_token,
        "POST",
        "/vendor-contacts",
        body={
            "vendor_id": vendor["vendor_id"],
            "name": "Sanitized Canary Contact",
            "email": "vendor-canary@example.edu",
        },
        expected_status=201,
    )
    case = request_json(
        base_url,
        reviewer_token,
        "POST",
        "/cases",
        body={
            "product_name": product["name"],
            "vendor_name": vendor["name"],
            "requester": {
                "name": "Sanitized Canary Requester",
                "email": "requester-canary@example.edu",
                "department": "Technology Review",
            },
            "use_case": "Disposable post-deploy vendor invitation reliability check.",
            "expected_users": 1,
            "platform": ["web"],
            "data_classification": "public",
            "estimated_cost_usd": 0,
            "integrations": [],
            "uses_sso": False,
            "uses_ai": False,
            "classroom_or_public_use": False,
        },
        expected_status=201,
    )
    issued = request_json(
        base_url,
        reviewer_token,
        "POST",
        f"/cases/{case['case_id']}/invites",
        body={"contact_id": contact["contact_id"]},
        expected_status=201,
    )
    invitation_token = issued.pop("token")
    opened = request_json(
        base_url,
        reviewer_token,
        "POST",
        "/vendor/invites/current/open",
        body={},
        vendor_token=invitation_token,
        expected_status=200,
    )
    if opened.get("invite", {}).get("case_id") != case["case_id"]:
        raise CanaryFailure("opened invitation was not scoped to the disposable case")
    request_json(
        base_url,
        reviewer_token,
        "POST",
        f"/invites/{issued['invite']['invite_id']}/revoke",
        body={},
        expected_status=200,
    )
    terminal = request_json(
        base_url,
        reviewer_token,
        "GET",
        "/vendor/invites/current",
        vendor_token=invitation_token,
        expected_status=410,
    )
    if terminal.get("error", {}).get("code") != "invite_revoked":
        raise CanaryFailure("revoked invitation did not return invite_revoked")
    return {"status": "ok", "case_id": case["case_id"], "invite_id": issued["invite"]["invite_id"]}


def main() -> int:
    try:
        result = run()
    except (CanaryFailure, urllib.error.URLError, json.JSONDecodeError, KeyError) as error:
        print(f"Invitation canary failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
