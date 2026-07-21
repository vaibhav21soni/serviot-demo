"""Smoke tests for the CRUD + health endpoints.

Run against a live stack:
    docker compose up -d
    BASE_URL=http://localhost:8080 pytest -q

Uses only the stdlib so no extra test deps are needed.
"""
import json
import os
import urllib.error
import urllib.request

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8080")


def _req(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            payload = resp.read()
            return resp.status, json.loads(payload) if payload else None
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, json.loads(payload) if payload else None


def test_health():
    status, body = _req("GET", "/health")
    assert status == 200
    assert body["status"] == "healthy"
    assert body["database"]["status"] == "up"


def test_crud_lifecycle():
    # create
    status, dev = _req("POST", "/devices", {"name": "sensor-1", "type": "temp"})
    assert status == 201
    assert dev["name"] == "sensor-1"
    dev_id = dev["id"]

    # read
    status, got = _req("GET", f"/devices/{dev_id}")
    assert status == 200 and got["id"] == dev_id

    # update
    status, upd = _req("PUT", f"/devices/{dev_id}", {"status": "online"})
    assert status == 200 and upd["status"] == "online"

    # list
    status, items = _req("GET", "/devices")
    assert status == 200 and any(d["id"] == dev_id for d in items)

    # delete
    status, _ = _req("DELETE", f"/devices/{dev_id}")
    assert status == 204

    # gone
    status, _ = _req("GET", f"/devices/{dev_id}")
    assert status == 404
