"""Tests for generator.connections: the database connection is created once, with an encrypted password, and never overwritten."""
import copy
import json
import unittest

from generator import connections

ENCRYPTED = {"type": "Embedded", "data": {"ciphertext": "AAAA", "iv": "BBBB"}}
PLAIN = "plain-password-for-tests"


class FakeGateway:
    def __init__(self, existing=None):
        self.existing = existing
        self.created = []
        self.encrypted = []

    def database_connection(self, name):
        return self.existing

    def encrypt(self, plain_text):
        self.encrypted.append(plain_text)
        return copy.deepcopy(ENCRYPTED)

    def create_database_connection(self, body):
        self.created.append(body)


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


if __name__ == "__main__":
    unittest.main()
