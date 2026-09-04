# -*- coding: utf-8 -*-
"""Start the simulator, Agent API, and V8 Streamlit frontend together."""
from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
from typing import Dict
from urllib.parse import urlparse

import requests


def _free_local_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        return int(listener.getsockname()[1])


def _local_endpoint(
    configured_url: str,
    *,
    default_port: int,
    label: str,
) -> tuple[str, str, int]:
    if not configured_url:
        host = "127.0.0.1"
        port = _free_local_port(host)
        return f"http://{host}:{port}", host, port
    parsed = urlparse(configured_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or default_port
    if parsed.scheme != "http" or host not in {"127.0.0.1", "localhost"}:
        raise SystemExit(
            f"start_demo.py only manages a local HTTP {label}; "
            f"start external services separately."
        )
    return f"http://{host}:{port}", host, port


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
    env.update(
        {
            "DRIVEMATE_SIMULATOR_TOKEN": simulator_token,
            "DRIVEMATE_SIMULATOR_URL": simulator_url,
            "DRIVEMATE_API_TOKEN": api_token,
            "DRIVEMATE_API_MODE": "http",
            "DRIVEMATE_BACKEND_URL": backend_url,
        }
    )

    simulator = None
    backend = None
    try:
        simulator = subprocess.Popen(
            [
                sys.executable,
                os.path.join(root, "simulator_server.py"),
                "--host",
                simulator_host,
                "--port",
                str(simulator_port),
                "--token",
                simulator_token,
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
                "--token",
                api_token,
            ],
            cwd=root,
            env=env,
        )
        _wait_for_backend_health(backend_url, api_token, backend)

        print(f"Cockpit simulator ready at {simulator_url}", flush=True)
        print(f"DriveMate Agent API ready at {backend_url}", flush=True)
        frontend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                os.path.join(root, "app.py"),
            ],
            cwd=root,
            env=env,
        )
        return frontend.wait()
    finally:
        _stop(backend)
        _stop(simulator)


if __name__ == "__main__":
    raise SystemExit(main())
