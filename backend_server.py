# -*- coding: utf-8 -*-
"""Authenticated local REST adapter for the DriveMate Agent service."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import unquote, urlsplit

from backend_service import AgentRunService, ServiceError


MAX_BODY_BYTES = 1024 * 1024
RUN_ACTION_RE = re.compile(
    r"^/api/v1/agent/runs/([^/]+)/(confirm|cancel)$"
)
AUDIT_RE = re.compile(r"^/api/v1/audit/runs/([^/]+)$")


class AgentApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address,
        handler_class,
        *,
        service: AgentRunService,
        token: str,
    ):
        super().__init__(server_address, handler_class)
        self.service = service
        self.token = token


class Handler(BaseHTTPRequestHandler):
    server_version = "DriveMateAgentAPI/1.0"

    @property
    def api_server(self) -> AgentApiServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: Any) -> None:
        print(
            "%s - - [%s] %s"
            % (self.address_string(), self.log_date_time_string(), fmt % args),
            flush=True,
        )

    def _authorized(self) -> bool:
        expected = "Bearer " + self.api_server.token
        provided = self.headers.get("Authorization", "")
        return bool(self.api_server.token) and hmac.compare_digest(
            provided, expected
        )

    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self._json(
            401,
            {
                "error": "unauthorized",
                "message": "A valid DriveMate API bearer token is required.",
            },
        )
        return False

    def _read_json(self) -> Dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ServiceError("Content-Length must be an integer.") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise ServiceError("Request body exceeds the 1 MiB limit.", 413)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ServiceError("Request body must contain valid UTF-8 JSON.") from exc
        if not isinstance(payload, dict):
            raise ServiceError("Request body must be a JSON object.")
        return payload

    def _handle(self, operation) -> None:
        try:
            payload = operation()
        except ServiceError as exc:
            self._json(
                exc.status_code,
                {"error": "request_failed", "message": str(exc)},
            )
        except Exception:
            traceback.print_exc()
            self._json(
                500,
                {
                    "error": "internal_error",
                    "message": "The Agent API failed unexpectedly; no success was reported.",
                },
            )
        else:
            self._json(200, payload)

    def do_GET(self) -> None:
        if not self._require_auth():
            return
        path = urlsplit(self.path).path
        if path == "/health":
            self._handle(self.api_server.service.health)
            return
        if path == "/api/v1/meta":
            self._handle(self.api_server.service.meta)
            return
        if path == "/api/v1/simulator/state":
            self._handle(self.api_server.service.simulator_state)
            return
        match = AUDIT_RE.fullmatch(path)
        if match:
            run_id = unquote(match.group(1))
            self._handle(lambda: self.api_server.service.audit_run(run_id))
            return
        self._json(404, {"error": "not_found", "message": "Route not found."})

    def do_POST(self) -> None:
        if not self._require_auth():
            return
        path = urlsplit(self.path).path
        if path == "/api/v1/agent/runs":
            self._handle(
                lambda: self.api_server.service.create_run(self._read_json())
            )
            return
        match = RUN_ACTION_RE.fullmatch(path)
        if match:
            run_id = unquote(match.group(1))
            action = match.group(2)
            if action == "confirm":
                self._handle(
                    lambda: self.api_server.service.confirm_run(
                        run_id, self._read_json()
                    )
                )
            else:
                self._handle(lambda: self.api_server.service.cancel_run(run_id))
            return
        self._json(404, {"error": "not_found", "message": "Route not found."})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--token", default=os.environ.get("DRIVEMATE_API_TOKEN", "")
    )
    args = parser.parse_args()
    token = str(args.token or "").strip()
    if not token:
        raise SystemExit(
            "DRIVEMATE_API_TOKEN is required; no hard-coded fallback is allowed."
        )

    server = AgentApiServer(
        (args.host, args.port),
        Handler,
        service=AgentRunService(),
        token=token,
    )
    print(
        "DriveMate Agent API listening on http://%s:%s"
        % (args.host, args.port),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
