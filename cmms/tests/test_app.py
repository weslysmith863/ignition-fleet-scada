"""The web service over a real socket. Skipped when FastAPI and uvicorn are not installed (they are only in the container)."""
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

try:
    import fastapi  # noqa: F401
    import uvicorn
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

BODY = {"site": "site1", "equipment": "Inv1", "fault_started_at": "2026-10-13T18:34:47.476Z", "summary": "Inverter fault"}


def send(base, method, path, body=None, raw=None, content_type="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    request = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": content_type} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8"), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8"), error.headers.get("Content-Type", "")


@unittest.skipUnless(AVAILABLE, "fastapi and uvicorn are not installed")
class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        os.environ["CMMS_DB"] = os.path.join(cls.folder.name, "cmms.sqlite3")  # read when cmms.app is imported
        from cmms import app as module
        cls.module = module
        app = module.app
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        cls.base = "http://127.0.0.1:%d" % port
        cls.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=10)
        cls.module.store.close()  # Windows cannot delete the folder while a connection is open
        cls.folder.cleanup()

    def test_01_health_starts_with_no_tickets(self):
        status, body, _ = send(self.base, "GET", "/health")
        self.assertEqual((status, json.loads(body)), (200, {"status": "ok", "tickets": 0}))

    def test_02_a_new_ticket_is_201_and_the_same_fault_again_is_200_with_the_same_ticket(self):
        status, body, _ = send(self.base, "POST", "/tickets", BODY)
        first = json.loads(body)
        self.assertEqual((status, first["created"], first["ticket"]["id"]), (201, True, 1))
        status, body, _ = send(self.base, "POST", "/tickets", dict(BODY, summary="a retry"))
        again = json.loads(body)
        self.assertEqual((status, again["created"], again["ticket"]), (200, False, first["ticket"]))

    def test_03_the_body_is_read_as_json_even_without_a_content_type(self):
        status, body, _ = send(self.base, "POST", "/tickets", dict(BODY, equipment="Inv2"), content_type="text/plain")
        self.assertEqual((status, json.loads(body)["ticket"]["equipment"]), (201, "Inv2"))

    def test_04_bad_requests_say_why(self):
        status, body, _ = send(self.base, "POST", "/tickets", raw=b"not json")
        self.assertEqual((status, json.loads(body)["detail"]), (400, "the body is not valid JSON"))
        status, body, _ = send(self.base, "POST", "/tickets", {"site": "site1"})
        self.assertEqual(status, 422)
        self.assertIn("equipment is required", json.loads(body)["detail"])

    def test_05_listing_one_ticket_and_the_page(self):
        status, body, _ = send(self.base, "GET", "/tickets")
        self.assertEqual((status, [t["id"] for t in json.loads(body)]), (200, [2, 1]))
        self.assertEqual(send(self.base, "GET", "/tickets/1")[0], 200)
        self.assertEqual(send(self.base, "GET", "/tickets/99")[0], 404)
        status, body, content_type = send(self.base, "GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn("Inverter fault", body)


if __name__ == "__main__":
    unittest.main()
