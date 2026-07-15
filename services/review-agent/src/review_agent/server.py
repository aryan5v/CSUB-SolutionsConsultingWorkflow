"""Standard-library HTTP server for the local review application API."""

from __future__ import annotations

import argparse
import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .api import LocalApiError, LocalReviewApi

_CASE_ROUTE = re.compile(r"^/cases/([^/]+)(?:/(.*))?$")


def create_server(
    api: LocalReviewApi | None = None, *, host: str = "127.0.0.1", port: int = 8787
) -> ThreadingHTTPServer:
    application = api or LocalReviewApi()

    class LocalRequestHandler(BaseHTTPRequestHandler):
        server_version = "CSUBLocalReview/0.1"

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def _dispatch(self, method: str) -> None:
            try:
                path = urlparse(self.path).path
                if path == "/api" or path.startswith("/api/"):
                    path = path[4:] or "/"
                if method == "GET" and path == "/health":
                    self._json(HTTPStatus.OK, {"status": "ok", "mode": "local", "simulated": True})
                    return
                if method == "GET" and path == "/review-queue":
                    self._json(HTTPStatus.OK, application.list_review_queue())
                    return
                if method == "POST" and path == "/cases":
                    self._json(HTTPStatus.CREATED, application.create_case(self._body()))
                    return

                match = _CASE_ROUTE.match(path)
                if match is None:
                    raise LocalApiError(404, "route_not_found", f"route {path} not found")
                case_id, suffix = match.groups()
                suffix = suffix or ""

                if method == "POST" and suffix == "documents":
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
                            case_id,
                            confirmed_match_id=confirmed,
                            reviewer_id=reviewer_id,
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
                else:
                    raise LocalApiError(404, "route_not_found", f"route {path} not found")
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
            content_type = self.headers.get_content_type()
            if content_type != "application/json":
                raise LocalApiError(415, "unsupported_media_type", "request body must be application/json")
            try:
                text = self.rfile.read(length).decode("utf-8")
                payload = json.loads(
                    text,
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(f"non-finite JSON number: {value}")
                    ),
                )
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
            if origin in {"http://127.0.0.1:5173", "http://localhost:5173"}:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

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
