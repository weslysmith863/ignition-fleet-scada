"""A small client for one gateway's REST API (ADR 0005). The API key comes from the gitignored .env and is never printed."""
import json
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
GATEWAYS = {"hub": (8090, "HUB_API_TOKEN"), "site1": (8091, "SITE1_API_TOKEN")}
DEVICE_TYPE = "com.inductiveautomation.opcua/device"
DATABASE_TYPE = "ignition/database-connection"
OPC_CONNECTION_TYPE = "ignition/opc-connection"
PROVIDER = "default"


class GatewayError(RuntimeError):
    pass


def env_value(variable):
    """A value from the gitignored .env. Callers must never print it."""
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*%s\s*=(.*)$" % re.escape(variable), line)
        if match:
            return match.group(1).strip().strip('"').strip("'")
    raise GatewayError("%s is not set in .env" % variable)


class RestGateway:
    def __init__(self, site, provider=PROVIDER):
        if site not in GATEWAYS:
            raise GatewayError("no gateway is configured for site %r (known: %s)" % (site, sorted(GATEWAYS)))
        port, variable = GATEWAYS[site]
        self.site = site
        self.provider = provider  # the tag provider the tag calls below work in; a site gateway's own tags are in default
        self._base = "http://127.0.0.1:%d/data/api/v1" % port
        self._key = env_value(variable)

    def _call(self, method, path, body=None, content_type="application/json", allow_404=False):
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        headers = {"X-Ignition-API-Token": self._key}
        if data is not None:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self._base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 404 and allow_404:
                return None
            raise GatewayError("%s %s -> HTTP %d: %s" % (method, path, error.code, error.read()[:300].decode(errors="replace")))
        except urllib.error.URLError as error:
            raise GatewayError("cannot reach the %s gateway: %s" % (self.site, error.reason))

    def device_settings_schema(self):
        """The Modbus TCP settings schema, whose defaults the device body is built from."""
        types = self._call("GET", "/resources/type/" + DEVICE_TYPE)
        modbus = next(e for e in types["extensionPoints"] if e["typeId"] == "ModbusTcp")
        return modbus["addComponent"]["settingsSchema"]["properties"]

    def device(self, name):
        """The device resource, or None when it does not exist."""
        return self._call("GET", "/resources/find/%s/%s" % (DEVICE_TYPE, urllib.parse.quote(name)), allow_404=True)

    def create_device(self, body):
        return self._call("POST", "/resources/" + DEVICE_TYPE, [body])

    def wait_for_devices(self, timeout_s=30.0, poll_s=1.0):
        """Wait until every device resource reports healthy (the Devices line of the overview, "n/n healthy resources").

        Returns False on timeout. Instances imported before their device is ready can get stuck on Bad_NodeIdUnknown
        (Phase 1 finding 26)."""
        deadline = time.monotonic() + timeout_s
        while True:
            overview = self._call("GET", "/overview/connections")
            for item in overview.get("items", []):
                if item.get("title") == "Devices" and item.get("lines"):
                    match = re.match(r"(\d+)/(\d+)", item["lines"][0].get("text", ""))
                    if match and int(match.group(2)) > 0 and match.group(1) == match.group(2):
                        return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(poll_s)

    def encrypt(self, plain_text):
        """Turn a plain value into an embedded secret only this gateway can read (finding 8). The result goes into a resource
        config in place of the plain value, so the config can be stored and exported without exposing it. The route returns
        the five encrypted fields bare; a resource wants them wrapped as {"type": "Embedded", "data": ...} (finding 27)."""
        request = urllib.request.Request(self._base + "/encryption/encrypt", data=plain_text.encode("utf-8"), method="POST",
                                         headers={"X-Ignition-API-Token": self._key, "Content-Type": "text/plain"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return {"type": "Embedded", "data": json.loads(response.read().decode("utf-8"))}
        except urllib.error.HTTPError as error:
            raise GatewayError("POST /encryption/encrypt -> HTTP %d" % error.code)  # the body could echo the secret: not shown
        except urllib.error.URLError as error:
            raise GatewayError("cannot reach the %s gateway: %s" % (self.site, error.reason))

    def project(self, name):
        """The project's details, or None when it does not exist."""
        return self._call("GET", "/projects/find/%s" % urllib.parse.quote(name), allow_404=True)

    def import_project(self, name, zip_bytes, overwrite=False):
        """Import a project zip (project.json at its root). Without overwrite, an existing project of that name is refused."""
        query = urllib.parse.urlencode({"overwrite": "true"}) if overwrite else ""
        path = "/projects/import/%s%s" % (urllib.parse.quote(name), "?" + query if query else "")
        request = urllib.request.Request(self._base + path, data=zip_bytes, method="POST",
                                         headers={"X-Ignition-API-Token": self._key, "Content-Type": "application/zip"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as error:
            raise GatewayError("POST %s -> HTTP %d: %s" % (path, error.code, error.read()[:300].decode(errors="replace")))
        except urllib.error.URLError as error:
            raise GatewayError("cannot reach the %s gateway: %s" % (self.site, error.reason))

    def scan_projects(self):
        """Ask the gateway to rescan project files (a project imported through the API is picked up by itself, but a scan is cheap)."""
        return self._call("POST", "/scan/projects")

    def opc_connection(self, name):
        """The OPC UA client connection resource, or None when it does not exist."""
        return self._call("GET", "/resources/find/%s/%s" % (OPC_CONNECTION_TYPE, urllib.parse.quote(name)), allow_404=True)

    def update_resource(self, resource_type, resource):
        """Modify one resource (PUT). Only the fields the API accepts are sent, and the signature must match the gateway's
        current copy, so a change made since this resource was read is refused instead of overwritten."""
        keep = ("name", "collection", "enabled", "description", "signature", "config", "backupConfig")
        return self._call("PUT", "/resources/" + resource_type, [{key: resource[key] for key in keep if key in resource}])

    def database_connection(self, name):
        """The database connection resource, or None when it does not exist."""
        return self._call("GET", "/resources/find/%s/%s" % (DATABASE_TYPE, urllib.parse.quote(name)), allow_404=True)

    def create_database_connection(self, body):
        return self._call("POST", "/resources/" + DATABASE_TYPE, [body])

    def tag(self, path):
        """One tag, folder, or UDT instance without its children, or None. A missing path answers with tagType
        Unknown and HTTP 200, not a 404 (Phase 1 finding 25)."""
        query = urllib.parse.urlencode({"provider": self.provider, "type": "json", "path": path, "recursive": "false"})
        found = self._call("GET", "/tags/export?" + query)
        return None if found.get("tagType") == "Unknown" else found

    def export_tags(self, path):
        """The tag JSON under a path, children included. `_types_` is the folder that holds the UDT definitions."""
        query = urllib.parse.urlencode({"provider": self.provider, "type": "json", "path": path})
        return self._call("GET", "/tags/export?" + query)

    def import_tags(self, payload, path=None, policy="Abort"):
        """Import tag JSON. Abort means a name collision stops the import, so nothing is ever overwritten."""
        query = {"provider": self.provider, "type": "json", "collisionPolicy": policy}
        if path:
            query["path"] = path
        return self._call("POST", "/tags/import?" + urllib.parse.urlencode(query), json.dumps(payload).encode("utf-8"),
                          content_type="application/octet-stream")
