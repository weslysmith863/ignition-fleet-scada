"""Phase 1 scale-factor spike: create the SpikeSF Modbus device and test tags on site1 through the REST API.

Saved as it was run in a scratch session on 2026-10-03; not re-run from this file. Reads the site1 API key from the
gitignored .env and never prints it. Start server.py first (it listens on 127.0.0.1:15020).
"""
import json
import pathlib
import re
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[3]
BASE = "http://127.0.0.1:8091"


def api_key():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*SITE1_API_TOKEN\s*=(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    raise SystemExit("SITE1_API_TOKEN not found in .env")


def call(method, path, body=None, content_type="application/json"):
    data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
    headers = {"X-Ignition-API-Token": api_key()}
    if data is not None:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def schema_defaults(props):
    """Nested defaults from the device settings schema. The device resource needs every settings group."""
    out = {}
    for name, spec in props.items():
        if spec.get("type") == "object" and "properties" in spec:
            out[name] = schema_defaults(spec["properties"])
        elif spec.get("default") is not None:
            out[name] = spec["default"]
    return out


def create_device():
    types = call("GET", "/data/api/v1/resources/type/com.inductiveautomation.opcua/device")
    modbus = next(e for e in types["extensionPoints"] if e["typeId"] == "ModbusTcp")
    settings = schema_defaults(modbus["addComponent"]["settingsSchema"]["properties"])
    settings["connectivity"]["hostname"] = "host.docker.internal"  # the PC, as seen from the container
    settings["connectivity"]["port"] = 15020
    body = [{
        "name": "SpikeSF", "collection": "core", "enabled": True,
        "description": "Phase 1 scale-factor spike (ADR 0006); disposable",
        "config": {"profile": {"type": "ModbusTcp"}, "settings": settings},
    }]
    return call("POST", "/data/api/v1/resources/com.inductiveautomation.opcua/device", body)


def opc(name, data_type, item):
    return {"name": name, "tagType": "AtomicTag", "valueSource": "opc", "dataType": data_type,
            "opcServer": "Ignition OPC UA Server", "opcItemPath": "ns=1;s=[SpikeSF]" + item}


def inverter(unit):
    return {"name": "Inv%d" % unit, "tagType": "Folder", "tags": [
        opc("W", "Int2", "%d.HR40085" % unit),        # SunSpec W: wire address 40084, signed 16-bit
        opc("W_SF", "Int2", "%d.HR40086" % unit),
        opc("Hz", "Int2", "%d.HRUS40087" % unit),     # unsigned 16-bit
        opc("Hz_SF", "Int2", "%d.HR40088" % unit),
        {"name": "W_scaled", "tagType": "AtomicTag", "valueSource": "expr", "dataType": "Float8",
         "expression": "{[.]W} * pow(10, {[.]W_SF})"},
        {"name": "Hz_scaled", "tagType": "AtomicTag", "valueSource": "expr", "dataType": "Float8",
         "expression": "{[.]Hz} * pow(10, {[.]Hz_SF})"},
    ]}


def import_tags():
    payload = {"tags": [{"name": "SpikeSF", "tagType": "Folder", "tags": [inverter(1), inverter(2)]}]}
    return call("POST", "/data/api/v1/tags/import?provider=default&type=json&collisionPolicy=Overwrite",
                json.dumps(payload).encode(), content_type="application/octet-stream")


if __name__ == "__main__":
    print("device:", create_device()["success"])
    print("tags:", import_tags())
