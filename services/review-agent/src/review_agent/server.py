"""Standard-library HTTP server for the local review application API."""

from __future__ import annotations

import argparse
import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .api import LocalApiError, LocalReviewApi

_CASE_ROUTE = re.compile(r"^/cases/([^/]+)(?:/(.*))?$")
_RESOURCE_ROUTE = re.compile(r"^/(vendors|vendor-products|vendor-contacts)(?:/([^/]+))?$")
_INVITE_ROUTE = re.compile(r"^/invites/([^/]+)/(revoke|resend)$")
_VENDOR_TOKEN_ROUTE = re.compile(
    r"^/vendor/invites/([^/]+)(?:/(open|evidence|trust-center|answers|coverage|analyze|questions|finalize|status))?$"
)
_PROFILE_ROUTE = re.compile(r"^/review-profiles/([^/]+)(?:/(fixture-test|activate|rollback))?$")
_CATALOG_CONFIRM_ROUTE = re.compile(r"^/catalog/matches/([^/]+)/confirm$")
_IMPORT_ROUTE = re.compile(r"^/servicenow/imports/([^/]+)/(preview|create)$")


def create_server(
    api: LocalReviewApi | None = None, *, host: str = "127.0.0.1", port: int = 8787
) -> ThreadingHTTPServer:
    application = api or LocalReviewApi()

    class LocalRequestHandler(BaseHTTPRequestHandler):
        server_version = "CSUBLocalReview/0.2"

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def do_PATCH(self) -> None:  # noqa: N802
            self._dispatch("PATCH")

        def do_DELETE(self) -> None:  # noqa: N802
            self._dispatch("DELETE")

        def _dispatch(self, method: str) -> None:
            try:
                parsed = urlparse(self.path)
                path = parsed.path
                query = parse_qs(parsed.query, keep_blank_values=False)
                if path == "/api" or path.startswith("/api/"):
                    path = path[4:] or "/"
                if method == "GET" and path == "/health":
                    self._json(
                        HTTPStatus.OK,
                        {"status": "ok", "mode": "local", "simulated": True},
                    )
                    return
                if method == "GET" and path == "/review-queue":
                    self._json(HTTPStatus.OK, application.list_review_queue())
                    return
                if method == "POST" and path == "/cases":
                    self._json(HTTPStatus.CREATED, application.create_case(self._body()))
                    return
                if method == "GET" and path == "/integration-events":
                    self._json(HTTPStatus.OK, application.integration_events())
                    return
                if method == "POST" and path == "/reminders/run":
                    self._json(HTTPStatus.OK, application.run_reminder_sweep())
                    return
                if method == "GET" and path == "/catalog":
                    self._json(
                        HTTPStatus.OK,
                        application.list_catalog(
                            query.get("q", [None])[0],
                            query.get("limit", [None])[0],
                            query.get("offset", [None])[0],
                        ),
                    )
                    return
                if method == "GET" and path == "/catalog/search":
                    search = query.get("q", [""])[0]
                    vendor = query.get("vendor", [None])[0]
                    self._json(HTTPStatus.OK, application.search_catalog(search, vendor))
                    return
                catalog_confirmation = _CATALOG_CONFIRM_ROUTE.match(path)
                if catalog_confirmation is not None and method == "POST":
                    self._json(
                        HTTPStatus.OK,
                        application.confirm_catalog_match(
                            catalog_confirmation.group(1), self._body()
                        ),
                    )
                    return
                if path == "/review-profiles":
                    if method == "GET":
                        self._json(HTTPStatus.OK, application.list_profiles())
                    elif method == "POST":
                        self._json(
                            HTTPStatus.CREATED,
                            application.create_profile_draft(self._body()),
                        )
                    else:
                        self._not_found(path)
                    return

                resource = _RESOURCE_ROUTE.match(path)
                if resource is not None:
                    kind, resource_id = resource.groups()
                    self._dispatch_resource(application, method, kind, resource_id, query)
                    return

                invite_admin = _INVITE_ROUTE.match(path)
                if invite_admin is not None and method == "POST":
                    invite_id, action = invite_admin.groups()
                    result = (
                        application.revoke_vendor_invite(invite_id)
                        if action == "revoke"
                        else application.resend_vendor_invite(invite_id)
                    )
                    self._json(HTTPStatus.OK, result)
                    return

                vendor_route = _VENDOR_TOKEN_ROUTE.match(path)
                if vendor_route is not None:
                    token, action = vendor_route.groups()
                    self._dispatch_vendor(application, method, token, action)
                    return

                profile_route = _PROFILE_ROUTE.match(path)
                if profile_route is not None:
                    profile_id, action = profile_route.groups()
                    if method == "PATCH" and action is None:
                        result = application.update_profile_draft(profile_id, self._body())
                    elif method == "POST" and action == "fixture-test":
                        result = application.fixture_test_profile(profile_id, self._body())
                    elif method == "POST" and action == "activate":
                        result = application.activate_profile(profile_id)
                    elif method == "POST" and action == "rollback":
                        result = application.rollback_profile(profile_id)
                    else:
                        self._not_found(path)
                        return
                    self._json(HTTPStatus.OK, result)
                    return

                import_route = _IMPORT_ROUTE.match(path)
                if import_route is not None and method in {"GET", "POST"}:
                    external_id, action = import_route.groups()
                    if action == "preview" and method == "GET":
                        result = application.preview_servicenow_import(external_id)
                        status = HTTPStatus.OK
                    elif action == "create" and method == "POST":
                        result = application.create_from_servicenow_import(external_id)
                        status = HTTPStatus.CREATED
                    else:
                        self._not_found(path)
                        return
                    self._json(status, result)
                    return

                match = _CASE_ROUTE.match(path)
                if match is None:
                    self._not_found(path)
                    return
                case_id, suffix = match.groups()
                suffix = suffix or ""
                if method == "GET" and suffix == "research" and "token" in query:
                    raise LocalApiError(
                        400,
                        "token_in_url_forbidden",
                        "invitation tokens must not appear in URLs",
                    )
                self._dispatch_case(application, method, case_id, suffix)
            except LocalApiError as error:
                self._json(error.status, {"error": {"code": error.code, "message": str(error)}})
            except json.JSONDecodeError:
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": {"code": "invalid_json", "message": "request body must be valid JSON"}},
                )
            except Exception:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": {"code": "internal_error", "message": "local API request failed"}},
                )

        def _dispatch_resource(
            self,
            application: LocalReviewApi,
            method: str,
            kind: str,
            resource_id: str | None,
            query: dict[str, list[str]],
        ) -> None:
            if kind == "vendors":
                if method == "GET" and resource_id is None:
                    result, status = application.list_vendors(), HTTPStatus.OK
                elif method == "GET" and resource_id:
                    result, status = application.get_vendor_record(resource_id), HTTPStatus.OK
                elif method == "POST" and resource_id is None:
                    result, status = application.create_vendor_record(self._body()), HTTPStatus.CREATED
                elif method == "PATCH" and resource_id:
                    result, status = application.update_vendor_record(resource_id, self._body()), HTTPStatus.OK
                elif method == "DELETE" and resource_id:
                    result, status = application.delete_vendor_record(resource_id), HTTPStatus.OK
                else:
                    self._not_found(self.path)
                    return
            elif kind == "vendor-products":
                vendor_id = query.get("vendor_id", [None])[0]
                if method == "GET" and resource_id is None:
                    result, status = application.list_vendor_products(vendor_id), HTTPStatus.OK
                elif method == "GET" and resource_id:
                    result, status = application.get_vendor_product(resource_id), HTTPStatus.OK
                elif method == "POST" and resource_id is None:
                    result, status = application.create_vendor_product(self._body()), HTTPStatus.CREATED
                elif method == "PATCH" and resource_id:
                    result, status = application.update_vendor_product(resource_id, self._body()), HTTPStatus.OK
                elif method == "DELETE" and resource_id:
                    result, status = application.delete_vendor_product(resource_id), HTTPStatus.OK
                else:
                    self._not_found(self.path)
                    return
            else:
                vendor_id = query.get("vendor_id", [None])[0]
                if method == "GET" and resource_id is None:
                    result, status = application.list_vendor_contacts(vendor_id), HTTPStatus.OK
                elif method == "GET" and resource_id:
                    result, status = application.get_vendor_contact(resource_id), HTTPStatus.OK
                elif method == "POST" and resource_id is None:
                    result, status = application.create_vendor_contact(self._body()), HTTPStatus.CREATED
                elif method == "PATCH" and resource_id:
                    result, status = application.update_vendor_contact(resource_id, self._body()), HTTPStatus.OK
                elif method == "DELETE" and resource_id:
                    result, status = application.delete_vendor_contact(resource_id), HTTPStatus.OK
                else:
                    self._not_found(self.path)
                    return
            self._json(status, result)

        def _dispatch_vendor(
            self, application: LocalReviewApi, method: str, token: str, action: str | None
        ) -> None:
            if method == "GET" and action is None:
                result = application.resolve_vendor_invite(token)
            elif method == "POST" and action == "open":
                result = application.resolve_vendor_invite(token, mark_open=True)
            elif method == "POST" and action == "evidence":
                result = application.vendor_add_evidence(token, self._body())
            elif method == "POST" and action == "trust-center":
                result = application.vendor_set_trust_center(token, self._body())
            elif method == "POST" and action == "answers":
                result = application.vendor_save_answers(token, self._body())
            elif method == "POST" and action == "coverage":
                result = application.vendor_add_coverage(token, self._body())
            elif method == "POST" and action == "analyze":
                result = application.vendor_run_intake_analysis(token)
            elif method == "GET" and action == "questions":
                result = application.vendor_questions(token)
            elif method == "GET" and action == "status":
                result = application.vendor_review_status(token)
            elif method == "POST" and action == "finalize":
                result = application.vendor_finalize(token)
            else:
                self._not_found(self.path)
                return
            self._json(HTTPStatus.OK, result)

        def _dispatch_case(
            self, application: LocalReviewApi, method: str, case_id: str, suffix: str
        ) -> None:
            if method == "GET" and suffix == "research":
                self._json(HTTPStatus.OK, application.get_case_research(case_id))
            elif method == "POST" and suffix == "documents":
                self._json(HTTPStatus.CREATED, application.add_document(case_id, self._body()))
            elif method == "POST" and suffix == "analyze":
                body = self._body()
                confirmed = body.get("confirmed_match_id")
                reviewer_id = body.get("reviewer_id")
                if confirmed is not None and not isinstance(confirmed, str):
                    raise LocalApiError(400, "invalid_match", "confirmed_match_id must be a string")
                if reviewer_id is not None and not isinstance(reviewer_id, str):
                    raise LocalApiError(400, "invalid_reviewer", "reviewer_id must be a string")
                self._json(
                    HTTPStatus.ACCEPTED,
                    application.analyze_case(
                        case_id, confirmed_match_id=confirmed, reviewer_id=reviewer_id
                    ),
                )
            elif method == "GET" and suffix == "stream":
                state = application.get_state(case_id)
                payload = f"event: state\ndata: {json.dumps(state, separators=(',', ':'))}\n\n"
                self._text(HTTPStatus.OK, payload, "text/event-stream; charset=utf-8")
            elif method == "POST" and suffix == "review":
                self._json(HTTPStatus.OK, application.review_case(case_id, self._body()))
            elif method == "POST" and suffix == "servicenow/preview":
                self._json(HTTPStatus.OK, application.preview_servicenow(case_id))
            elif method == "POST" and suffix == "servicenow/commit":
                self._json(HTTPStatus.OK, application.commit_servicenow(case_id, self._body()))
            elif method == "GET" and suffix == "packet":
                self._json(HTTPStatus.OK, application.get_packet(case_id))
            elif method == "GET" and suffix == "packet/pdf":
                self._json(HTTPStatus.OK, application.get_packet_pdf(case_id))
            elif method == "POST" and suffix == "invites":
                self._json(HTTPStatus.CREATED, application.issue_vendor_invite(case_id, self._body()))
            elif method == "GET" and suffix == "invites":
                self._json(HTTPStatus.OK, application.list_case_invites(case_id))
            elif method == "GET" and suffix == "reminders":
                self._json(HTTPStatus.OK, application.reminder_history(case_id))
            elif method == "POST" and suffix == "reminders/pause":
                self._json(HTTPStatus.OK, application.set_reminders_paused(case_id, True))
            elif method == "POST" and suffix == "reminders/resume":
                self._json(HTTPStatus.OK, application.set_reminders_paused(case_id, False))
            elif method == "POST" and suffix == "review-runs":
                self._json(HTTPStatus.CREATED, application.create_review_run(case_id, self._body()))
            elif method == "GET" and suffix == "review-runs":
                self._json(HTTPStatus.OK, application.list_review_runs(case_id))
            else:
                self._not_found(self.path)

        def _not_found(self, path: str) -> None:
            raise LocalApiError(404, "route_not_found", f"route {path} not found")

        def _body(self) -> dict[str, Any]:
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError as error:
                raise LocalApiError(400, "invalid_length", "invalid Content-Length") from error
            if length < 0:
                raise LocalApiError(400, "invalid_length", "Content-Length cannot be negative")
            if length == 0:
                return {}
            if length > 1_000_000:
                raise LocalApiError(413, "body_too_large", "request body exceeds local API limit")
            if self.headers.get_content_type() != "application/json":
                raise LocalApiError(415, "unsupported_media_type", "request body must be application/json")

            def reject_constant(value: str) -> None:
                raise ValueError(f"non-finite JSON number: {value}")

            try:
                text = self.rfile.read(length).decode("utf-8")
                payload = json.loads(text, parse_constant=reject_constant)
            except UnicodeDecodeError as error:
                raise LocalApiError(400, "invalid_encoding", "request body must be UTF-8") from error
            except (json.JSONDecodeError, ValueError) as error:
                raise LocalApiError(400, "invalid_json", "request body must be strict JSON") from error
            if not isinstance(payload, dict):
                raise LocalApiError(400, "invalid_body", "request body must be a JSON object")
            return payload

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _text(self, status: int, payload: str, content_type: str) -> None:
            body = payload.encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _cors_headers(self) -> None:
            origin = self.headers.get("Origin")
            allowed_origin: str | None = None
            if origin == "http://127.0.0.1:5173":
                allowed_origin = "http://127.0.0.1:5173"
            elif origin == "http://localhost:5173":
                allowed_origin = "http://localhost:5173"
            if allowed_origin is not None:
                self.send_header("Access-Control-Allow-Origin", allowed_origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer((host, port), LocalRequestHandler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local CSUB review API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = create_server(host=args.host, port=args.port)
    print(f"Local review API listening on http://{args.host}:{args.port}/api")
    print("Sanitized deterministic data only; ServiceNow operations are simulated.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
