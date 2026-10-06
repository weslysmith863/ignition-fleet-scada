"""Tests for generator.connections: the database connection is created once, with an encrypted password, and never overwritten."""
import copy
import json
import unittest

from generator import connections

ENCRYPTED = {"type": "Embedded", "data": {"ciphertext": "AAAA", "iv": "BBBB"}}
PLAIN = "plain-password-for-tests"


class FakeGateway:
    def __init__(self, existing=None, historian=None):
        self.existing = existing
        self.historian = historian
        self.created = []
        self.encrypted = []
        self.writes = []  # the order of changes: "connection", "historian"

    def database_connection(self, name):
        return self.existing

    def encrypt(self, plain_text):
        self.encrypted.append(plain_text)
        return copy.deepcopy(ENCRYPTED)

    def create_database_connection(self, body):
        self.created.append(body)
        self.existing = copy.deepcopy(body)  # a real gateway remembers what was created
        self.writes.append("connection")

    def historian_provider(self, name):
        return self.historian

    def create_historian_provider(self, body):
        self.historian = body
        self.writes.append("historian")


class ConnectionTests(unittest.TestCase):
    def test_the_body_points_at_the_postgres_service_and_carries_only_the_encrypted_password(self):
        body = connections.connection_body("fleet", "fleet", ENCRYPTED)
        self.assertEqual(body["name"], "fleetdb")
        self.assertEqual(body["config"]["driver"], "PostgreSQL")
        self.assertEqual(body["config"]["translator"], "POSTGRES")
        self.assertEqual(body["config"]["connectURL"], "jdbc:postgresql://postgres:5432/fleet")
        self.assertEqual(body["config"]["password"], ENCRYPTED)
        self.assertNotIn(PLAIN, json.dumps(body))

    def test_a_missing_connection_is_created_with_the_password_encrypted_first(self):
        gateway = FakeGateway()
        lines, drift = connections.apply_connection(gateway, "fleet", "fleet", PLAIN)
        self.assertEqual((lines, drift), (["created connection fleetdb"], False))
        self.assertEqual(gateway.encrypted, [PLAIN])
        self.assertEqual(len(gateway.created), 1)
        self.assertEqual(gateway.created[0]["config"]["password"], ENCRYPTED)
        self.assertNotIn(PLAIN, json.dumps(gateway.created))

    def test_a_dry_run_changes_nothing_and_does_not_even_encrypt(self):
        gateway = FakeGateway()
        lines, _ = connections.apply_connection(gateway, "fleet", "fleet", PLAIN, dry_run=True)
        self.assertTrue(lines[0].startswith("would create connection fleetdb"))
        self.assertNotIn(PLAIN, lines[0])
        self.assertEqual((gateway.created, gateway.encrypted), ([], []))

    def test_an_existing_matching_connection_is_left_alone(self):
        gateway = FakeGateway(existing=connections.connection_body("fleet", "fleet", ENCRYPTED))
        lines, drift = connections.apply_connection(gateway, "fleet", "fleet", PLAIN)
        self.assertEqual((lines, drift), (["unchanged: connection fleetdb"], False))
        self.assertEqual((gateway.created, gateway.encrypted), ([], []))

    def test_a_connection_pointing_somewhere_else_is_reported_as_drift_and_not_fixed(self):
        existing = connections.connection_body("fleet", "fleet", ENCRYPTED)
        existing["config"]["connectURL"] = "jdbc:postgresql://localhost:5432/fleet"
        gateway = FakeGateway(existing=existing)
        lines, drift = connections.apply_connection(gateway, "fleet", "fleet", PLAIN)
        self.assertTrue(drift)
        self.assertEqual(len(lines), 1)
        self.assertIn("connectURL is 'jdbc:postgresql://localhost:5432/fleet'", lines[0])
        self.assertEqual((gateway.created, gateway.encrypted), ([], []))


class HistorianTests(unittest.TestCase):
    """The SQL Historian provider `Historian` that logs to fleetdb: created once, never overwritten."""

    def test_the_body_is_a_sql_historian_on_fleetdb_with_the_settings_site_1_runs(self):
        body = connections.historian_body("fleetdb")
        self.assertEqual((body["name"], body["collection"], body["enabled"]), ("Historian", "core", True))
        self.assertEqual(body["config"]["profile"], {"type": "SqlHistorian"})
        settings = body["config"]["settings"]
        self.assertEqual(settings["database"], "fleetdb")
        self.assertEqual(settings["partition"], {"enabled": True, "size": 1, "sizeUnits": "MONTH", "partitionSeedQueryLimit": 2,
                                                 "optimized": False, "optimizedWindowSeconds": 60})
        self.assertEqual(settings["pruning"], {"enabled": True, "age": 1, "ageUnits": "MONTH"})  # the form default, to revisit
        self.assertEqual((settings["trackSce"], settings["staleMultiplier"]), (True, 2))

    def test_the_body_carries_no_password(self):
        self.assertNotIn("assword", json.dumps(connections.historian_body("fleetdb")))

    def test_each_body_is_a_fresh_copy(self):
        first = connections.historian_body("fleetdb")
        first["config"]["settings"]["pruning"]["age"] = 99
        self.assertEqual(connections.historian_body("fleetdb")["config"]["settings"]["pruning"]["age"], 1)

    def test_a_missing_provider_is_created(self):
        gateway = FakeGateway()
        lines, drift = connections.apply_historian(gateway, "fleetdb")
        self.assertEqual((lines, drift), (["created Historian provider Historian"], False))
        self.assertEqual(gateway.historian["name"], "Historian")

    def test_a_dry_run_changes_nothing(self):
        gateway = FakeGateway()
        lines, _ = connections.apply_historian(gateway, "fleetdb", dry_run=True)
        self.assertEqual(lines, ["would create Historian provider Historian (SQL Historian on fleetdb)"])
        self.assertIsNone(gateway.historian)

    def test_an_existing_matching_provider_is_left_alone(self):
        gateway = FakeGateway(historian=connections.historian_body("fleetdb"))
        lines, drift = connections.apply_historian(gateway, "fleetdb")
        self.assertEqual((lines, drift, gateway.writes), (["unchanged: Historian provider Historian"], False, []))

    def test_a_provider_on_another_database_is_reported_as_drift_and_not_fixed(self):
        existing = connections.historian_body("fleetdb")
        existing["config"]["settings"]["database"] = "otherdb"
        gateway = FakeGateway(historian=existing)
        lines, drift = connections.apply_historian(gateway, "fleetdb")
        self.assertTrue(drift)
        self.assertEqual(lines, ["DRIFT: Historian provider Historian: database is 'otherdb', wanted 'fleetdb'"])
        self.assertEqual(gateway.writes, [])
        self.assertEqual(gateway.historian["config"]["settings"]["database"], "otherdb")

    def test_a_provider_of_another_type_is_reported_as_drift(self):
        existing = connections.historian_body("fleetdb")
        existing["config"]["profile"]["type"] = "CoreHistorian"
        lines, drift = connections.apply_historian(FakeGateway(historian=existing), "fleetdb")
        self.assertTrue(drift)
        self.assertIn("type is 'CoreHistorian', wanted 'SqlHistorian'", lines[0])


class ApplyAllTests(unittest.TestCase):
    def test_the_database_connection_is_created_before_the_provider_that_uses_it(self):
        gateway = FakeGateway()
        lines, drift = connections.apply_all(gateway, "fleet", "fleet", PLAIN)
        self.assertEqual(gateway.writes, ["connection", "historian"])
        self.assertEqual((lines, drift), (["created connection fleetdb", "created Historian provider Historian"], False))

    def test_a_second_run_changes_nothing(self):
        gateway = FakeGateway()
        connections.apply_all(gateway, "fleet", "fleet", PLAIN)
        gateway.writes.clear()
        lines, drift = connections.apply_all(gateway, "fleet", "fleet", PLAIN)
        self.assertEqual((gateway.writes, drift), ([], False))
        self.assertEqual(lines, ["unchanged: connection fleetdb", "unchanged: Historian provider Historian"])

    def test_a_dry_run_changes_nothing(self):
        gateway = FakeGateway()
        lines, _ = connections.apply_all(gateway, "fleet", "fleet", PLAIN, dry_run=True)
        self.assertEqual((gateway.writes, gateway.encrypted), ([], []))
        self.assertEqual(len(lines), 2)

    def test_drift_in_either_one_is_reported(self):
        existing = connections.connection_body("fleet", "fleet", ENCRYPTED)
        existing["config"]["username"] = "someone"
        gateway = FakeGateway(existing=existing)
        _, drift = connections.apply_all(gateway, "fleet", "fleet", PLAIN)
        self.assertTrue(drift)


if __name__ == "__main__":
    unittest.main()
