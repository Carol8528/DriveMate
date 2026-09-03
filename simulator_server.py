# -*- coding: utf-8 -*-
"""独立可验证的车机/座舱模拟器。

启动：DRIVEMATE_SIMULATOR_TOKEN=<runtime-secret> python simulator_server.py
所有控制接口要求 Bearer 鉴权；执行后写入 SQLite，并可通过 /v1/state 复查状态。
"""
import argparse
import json
import os
import sqlite3
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DRIVEMATE_SIMULATOR_DB", os.path.join(BASE_DIR, "data", "simulator_state.db"))
TOKEN = os.environ.get("DRIVEMATE_SIMULATOR_TOKEN", "")


def now():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with conn() as c:
        c.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS receipts(receipt_id TEXT PRIMARY KEY, endpoint TEXT NOT NULL, payload_json TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL);
            """
        )


def set_state(key, value):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO state(key,value_json,updated_at) VALUES (?,?,?)", (key, json.dumps(value, ensure_ascii=False), now()))


def get_state():
    with conn() as c:
        rows = c.execute("SELECT key,value_json,updated_at FROM state ORDER BY key").fetchall()
    out = {}
    for r in rows:
        out[r["key"]] = {"value": json.loads(r["value_json"]), "updated_at": r["updated_at"]}
    return out


def receipt(endpoint, payload, result):
    rid = "SIM-" + uuid.uuid4().hex[:18]
    with conn() as c:
        c.execute("INSERT INTO receipts VALUES (?,?,?,?,?)", (rid, endpoint, json.dumps(payload, ensure_ascii=False), json.dumps(result, ensure_ascii=False), now()))
    result["receipt_id"] = rid
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "DriveMateCockpitSimulator/1.0"

    def log_message(self, fmt, *args):
        pass

    def _authorized(self):
        return bool(TOKEN) and self.headers.get("Authorization", "") == "Bearer " + TOKEN

    def _json(self, status, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _require_auth(self):
        if not self._authorized():
            self._json(401, {"success": False, "status": "unauthorized", "summary": "invalid bearer token"})
            return False
        return True

    def do_GET(self):
        if not self._require_auth():
            return
        if self.path == "/health":
            self._json(200, {"success": True, "service": "cockpit-simulator", "authenticated": True, "time": now()})
            return
        if self.path == "/v1/state":
            self._json(200, {"success": True, "state": get_state(), "time": now()})
            return
        self._json(404, {"success": False, "summary": "not found"})

    def do_POST(self):
        if not self._require_auth():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json(400, {"success": False, "summary": "invalid json"})
            return
        args = payload.get("arguments") or {}
        path = self.path

        if path == "/v1/cabin/climate":
            state = {"zone": args.get("zone", "all"), "temperature": args.get("temperature"), "fan_speed": args.get("fan_speed"), "mode": args.get("mode", "auto"), "active": True}
            set_state("climate", state)
            result = {"success": True, "status": "executed", "summary": "空调控制已由座舱模拟器执行", "verified_state": state}
        elif path == "/v1/cabin/seat":
            state = {"seat_position": args.get("seat_position", "driver"), "mode": args.get("mode", "massage"), "intensity": args.get("intensity", 2), "active": True}
            set_state("seat", state)
            result = {"success": True, "status": "executed", "summary": "座椅控制已由座舱模拟器执行", "verified_state": state}
        elif path == "/v1/cabin/media":
            state = {"source": args.get("source", "提神歌单"), "genre": args.get("genre", "music"), "playing": True}
            set_state("media", state)
            result = {"success": True, "status": "executed", "summary": "媒体播放已由座舱模拟器执行", "verified_state": state}
        elif path == "/v1/cabin/ambient":
            state = {"scene": args.get("scene", "relax"), "active": True}
            set_state("ambient", state)
            result = {"success": True, "status": "executed", "summary": "氛围模式已由座舱模拟器执行", "verified_state": state}
        elif path == "/v1/navigation/route":
            state = {"destination": args.get("destination", "最近安全服务区"), "status": "guidance_started"}
            set_state("navigation", state)
            result = {"success": True, "status": "executed", "summary": "导航已启动", "verified_state": state}
        elif path == "/v1/vehicle/contact":
            ctx = payload.get("context") or {}
            distance = ctx.get("distance_m")
            if distance is None or float(distance) > 100.0:
                self._json(409, {"success": False, "status": "safety_blocked", "summary": "模拟器拒绝：未通过 100 米距离校验"})
                return
            state = {"action": args.get("action", "both"), "duration_seconds": args.get("duration_seconds", 3), "distance_m": distance, "executed": True}
            set_state("vehicle_contact", state)
            result = {"success": True, "status": "executed", "summary": "车辆闪灯/鸣笛动作已执行", "verified_state": state}
        else:
            self._json(404, {"success": False, "summary": "not found"})
            return

        result = receipt(path, payload, result)
        self._json(200, result)


def main():
    global TOKEN, DB_PATH
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--token", default="")
    p.add_argument("--db", default="")
    a = p.parse_args()
    if a.token:
        TOKEN = a.token
    if a.db:
        DB_PATH = a.db
    if not TOKEN:
        raise SystemExit("DRIVEMATE_SIMULATOR_TOKEN is required; no hard-coded fallback is allowed.")
    init_db()
    print("Cockpit simulator listening on http://%s:%s" % (a.host, a.port), flush=True)
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
