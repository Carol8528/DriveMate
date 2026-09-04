# -*- coding: utf-8 -*-
"""Start the simulator, Agent API, and DriveMate web frontend together."""
from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from typing import Dict
from urllib.parse import urlparse

import requests


def _free_local_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        return int(listener.getsockname()[1])


def _available_port(host: str, preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind((host, preferred))
        except OSError:
            return _free_local_port(host)
    return preferred


def _local_endpoint(
    configured_url: str,
    *,
    default_port: int,
    label: str,
) -> tuple[str, str, int]:
    if not configured_url:
        host = "127.0.0.1"
        port = _available_port(host, default_port)
        return f"http://{host}:{port}", host, port
    parsed = urlparse(configured_url)
    host = parsed.hostname or "127.0.0.1"
    requested_port = parsed.port or default_port
    if parsed.scheme != "http" or host not in {"127.0.0.1", "localhost"}:
        raise SystemExit(
            f"start_demo.py only manages a local HTTP {label}; "
            f"start external services separately."
        )
    port = _available_port(host, requested_port)
    if port != requested_port:
        print(
            f"Configured {label} port {requested_port} is busy; using {port}.",
            flush=True,
        )
    return f"http://{host}:{port}", host, port


def _validated_bind_host(
    configured_host: str | None,
    *,
    default_host: str,
    label: str,
) -> str:
    host = (configured_host or default_host).strip().lower()
    if host not in {"127.0.0.1", "localhost", "0.0.0.0", "::"}:
        raise SystemExit(
            f"{label} bind host must be localhost or a wildcard address."
        )
    return host


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    value = raw_value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise SystemExit(f"{name} must be a boolean value.")


def _wait_for_health(
    base_url: str,
    token: str,
    process: subprocess.Popen,
    *,
    timeout_s: float,
    require_authenticated_flag: bool,
) -> Dict[str, object]:
    deadline = time.time() + timeout_s
    last_error = ""
    headers = {"Authorization": "Bearer " + token}
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Service exited before becoming healthy (exit={process.returncode})."
            )
        try:
            response = requests.get(
                base_url.rstrip("/") + "/health",
                headers=headers,
                timeout=0.8,
            )
            if response.status_code == 200:
                data = response.json() if response.content else {}
                if data.get("ok") is True or (
                    require_authenticated_flag
                    and data.get("authenticated") is True
                ):
                    return data
                last_error = "health response did not confirm readiness"
            elif response.status_code in (401, 403):
                last_error = "health authentication failed"
            else:
                last_error = f"health returned HTTP {response.status_code}"
        except (requests.RequestException, ValueError) as exc:
            last_error = str(exc)
        time.sleep(0.15)
    raise RuntimeError(
        f"Service did not become healthy within {timeout_s:.1f}s: "
        f"{last_error or 'unknown error'}"
    )


def _wait_for_authenticated_health(
    base_url: str,
    token: str,
    process: subprocess.Popen,
    timeout_s: float = 10.0,
):
    return _wait_for_health(
        base_url,
        token,
        process,
        timeout_s=timeout_s,
        require_authenticated_flag=True,
    )


def _wait_for_backend_health(
    base_url: str,
    token: str,
    process: subprocess.Popen,
    timeout_s: float = 10.0,
):
    return _wait_for_health(
        base_url,
        token,
        process,
        timeout_s=timeout_s,
        require_authenticated_flag=False,
    )


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _open_frontend(url: str) -> None:
    try:
        if webbrowser.open(url, new=2):
            return
    except webbrowser.Error:
        pass
    if hasattr(os, "startfile"):
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return
        except OSError:
            pass
    print(f"Open this URL in your browser: {url}", flush=True)


def main() -> int:
    root = os.path.dirname(os.path.abspath(__file__))
    env = os.environ.copy()
    simulator_token = secrets.token_urlsafe(32)
    api_token = secrets.token_urlsafe(32)

    simulator_url, simulator_host, simulator_port = _local_endpoint(
        str(os.environ.get("DRIVEMATE_SIMULATOR_URL") or "").strip(),
        default_port=8765,
        label="cockpit simulator",
    )
    backend_url, backend_host, backend_port = _local_endpoint(
        str(os.environ.get("DRIVEMATE_BACKEND_URL") or "").strip(),
        default_port=8000,
        label="Agent API",
    )
    frontend_url, frontend_host, frontend_port = _local_endpoint(
        str(os.environ.get("DRIVEMATE_FRONTEND_URL") or "").strip(),
        default_port=8501,
        label="web frontend",
    )
    frontend_bind_host = _validated_bind_host(
        os.environ.get("DRIVEMATE_FRONTEND_HOST"),
        default_host=frontend_host,
        label="web frontend",
    )
    skip_frontend_build = _env_flag("DRIVEMATE_SKIP_FRONTEND_BUILD")
    disable_browser = _env_flag("DRIVEMATE_NO_BROWSER")
    env.update(
        {
            "DRIVEMATE_SIMULATOR_TOKEN": simulator_token,
            "DRIVEMATE_SIMULATOR_URL": simulator_url,
            "DRIVEMATE_API_TOKEN": api_token,
            "DRIVEMATE_API_MODE": "http",
            "DRIVEMATE_BACKEND_URL": backend_url,
            "DRIVEMATE_FRONTEND_HOST": frontend_bind_host,
            "DRIVEMATE_FRONTEND_PORT": str(frontend_port),
        }
    )

    simulator = None
    backend = None
    frontend = None
    try:
        simulator = subprocess.Popen(
            [
                sys.executable,
                os.path.join(root, "simulator_server.py"),
                "--host",
                simulator_host,
                "--port",
                str(simulator_port),
                f"--token={simulator_token}",
            ],
            cwd=root,
            env=env,
        )
        _wait_for_authenticated_health(
            simulator_url, simulator_token, simulator
        )

        backend = subprocess.Popen(
            [
                sys.executable,
                os.path.join(root, "backend_server.py"),
                "--host",
                backend_host,
                "--port",
                str(backend_port),
                f"--token={api_token}",
            ],
            cwd=root,
            env=env,
        )
        _wait_for_backend_health(backend_url, api_token, backend)

        print(f"Cockpit simulator ready at {simulator_url}", flush=True)
        print(f"DriveMate Agent API ready at {backend_url}", flush=True)
        frontend_root = os.path.join(root, "frontend")
        node = shutil.which("node.exe") or shutil.which("node")
        if not node:
            raise RuntimeError("Node.js is required for the web frontend.")
        if skip_frontend_build:
            dist_index = os.path.join(frontend_root, "dist", "index.html")
            if not os.path.isfile(dist_index):
                raise RuntimeError(
                    "DRIVEMATE_SKIP_FRONTEND_BUILD requires frontend/dist/index.html."
                )
        else:
            npm = shutil.which("npm.cmd") or shutil.which("npm")
            if not npm:
                raise RuntimeError("npm is required to build the web frontend.")
            build = subprocess.run(
                [npm, "run", "build"],
                cwd=frontend_root,
                env=env,
                check=False,
            )
            if build.returncode != 0:
                raise RuntimeError("DriveMate web frontend build failed.")
        frontend = subprocess.Popen(
            [node, os.path.join(frontend_root, "server.mjs")],
            cwd=frontend_root,
            env=env,
        )
        _wait_for_health(
            frontend_url,
            "",
            frontend,
            timeout_s=10.0,
            require_authenticated_flag=False,
        )
        print(f"DriveMate web frontend ready at {frontend_url}", flush=True)
        if not disable_browser:
            _open_frontend(frontend_url)
        return frontend.wait()
    finally:
        _stop(frontend)
        _stop(backend)
        _stop(simulator)


if __name__ == "__main__":
    raise SystemExit(main())
