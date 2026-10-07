"""Tests for generator.providers: the hub's remote tag provider for a site is created once and never overwritten."""
import copy
import json
import unittest

from generator import providers


class FakeHub:
    def __init__(self, existing=None, healthy=True):
        self.existing = existing
        self.healthy = healthy
        self.created = []
        self.waited = []

    def tag_provider(self, name):
        return self.existing if self.existing and self.existing["name"] == name else None

    def create_tag_provider(self, body):
        self.created.append(body)
        self.existing = copy.deepcopy(body)

    def wait_for_healthy(self, resource_type, name, timeout_s=30.0, poll_s=1.0):
        self.waited.append((resource_type, name))
        return self.healthy


class BodyTests(unittest.TestCase):
    def test_the_provider_is_named_by_the_site_and_points_at_the_sites_default_provider(self):
        body = providers.remote_provider_body("site2")
        self.assertEqual((body["name"], body["collection"], body["enabled"]), ("site2", "core", True))
        self.assertEqual(body["config"]["profile"]["type"], "REMOTE")
        settings = body["config"]["settings"]
        self.assertEqual((settings["serverName"], settings["remoteProviderName"]), ("site2", "default"))

    def test_the_body_matches_the_hand_built_site1_provider(self):
        # What Wes built by hand on the hub on 2026-10-06 (Phase 2 finding 36).
        hand_built = {"profile": {"type": "REMOTE", "allowBackfill": False, "enableTagReferenceStore": True},
                      "settings": {"serverName": "site1", "remoteProviderName": "default", "historyMode": "GatewayNetwork",
                                   "historyDriverName": "", "historyProviderName": "", "alarmStatusEnabled": True,
                                   "alarmMode": "Queried"}}
        self.assertEqual(providers.remote_provider_body("site1")["config"], hand_built)

    def test_each_body_is_a_fresh_copy(self):
        first = providers.remote_provider_body("site2")
        first["config"]["settings"]["alarmMode"] = "changed"
        self.assertEqual(providers.remote_provider_body("site2")["config"]["settings"]["alarmMode"], "Queried")

    def test_the_body_carries_no_secret(self):
        self.assertNotIn("assword", json.dumps(providers.remote_provider_body("site2")))


class ApplyTests(unittest.TestCase):
    def test_a_missing_provider_is_created_then_waited_for(self):
        hub = FakeHub()
        lines, drift = providers.apply_provider(hub, "site2")
        self.assertEqual((lines, drift), (["created remote tag provider site2 (site2, provider default)"], False))
        self.assertEqual(hub.waited, [("ignition/tag-provider", "site2")])

    def test_a_provider_that_does_not_come_up_healthy_is_a_warning_not_a_failure(self):
        lines, drift = providers.apply_provider(FakeHub(healthy=False), "site2")
        self.assertFalse(drift)
        self.assertTrue(any(line.startswith("WARNING") and "site2" in line for line in lines), lines)

    def test_a_dry_run_changes_nothing(self):
        hub = FakeHub()
        lines, _ = providers.apply_provider(hub, "site2", dry_run=True)
        self.assertEqual(lines, ["would create remote tag provider site2 (site2, provider default)"])
        self.assertEqual((hub.created, hub.waited), ([], []))

    def test_a_matching_provider_is_left_alone(self):
        hub = FakeHub(existing=providers.remote_provider_body("site1"))
        lines, drift = providers.apply_provider(hub, "site1")
        self.assertEqual((lines, drift, hub.created), (["unchanged: remote tag provider site1"], False, []))

    def test_a_provider_that_points_elsewhere_is_reported_as_drift_and_not_fixed(self):
        existing = providers.remote_provider_body("site2")
        existing["config"]["settings"]["serverName"] = "site1"
        hub = FakeHub(existing=existing)
        lines, drift = providers.apply_provider(hub, "site2")
        self.assertTrue(drift)
        self.assertEqual(lines, ["DRIFT: remote tag provider site2: serverName is 'site1', wanted 'site2'"])
        self.assertEqual(hub.existing["config"]["settings"]["serverName"], "site1")

    def test_a_local_provider_with_the_same_name_is_reported_as_drift(self):
        existing = providers.remote_provider_body("site2")
        existing["config"]["profile"]["type"] = "STANDARD"
        lines, drift = providers.apply_provider(FakeHub(existing=existing), "site2")
        self.assertTrue(drift)
        self.assertIn("type is 'STANDARD', wanted 'REMOTE'", lines[0])


class OemProviderTests(unittest.TestCase):
    """An OEM site has no gateway to point at: the hub holds its tags in a local (STANDARD) provider named for the site."""

    def test_the_body_is_a_standard_provider_named_for_the_site(self):
        body = providers.provider_body("oem1")
        self.assertEqual((body["name"], body["collection"], body["enabled"]), ("oem1", "core", True))
        self.assertEqual(body["config"]["profile"]["type"], "STANDARD")
        self.assertNotIn("serverName", body["config"]["settings"])

    def test_the_body_matches_the_hubs_own_default_provider_settings(self):
        # What the hub's default provider held on 2026-10-06 (Phase 2 finding 42), apart from its name.
        self.assertEqual(providers.provider_body("oem1")["config"], {
            "profile": {"type": "STANDARD", "allowBackfill": False, "enableTagReferenceStore": True},
            "settings": {"defaultDatasourceName": None, "readPermissions": {"type": "AllOf", "securityLevels": []}, "readOnly": False,
                         "writePermissions": {"type": "AllOf", "securityLevels": []},
                         "editPermissions": {"type": "AllOf", "securityLevels": []}, "valuePersistence": "Database"}})

    def test_each_kind_of_site_gets_its_kind_of_provider(self):
        self.assertEqual(providers.provider_body("site2")["config"]["profile"]["type"], "REMOTE")
        self.assertEqual(providers.provider_body("oem3")["config"]["profile"]["type"], "STANDARD")

    def test_a_missing_oem_provider_is_created_without_waiting_on_a_remote_link(self):
        hub = FakeHub()
        lines, drift = providers.apply_provider(hub, "oem1")
        self.assertEqual((lines, drift), (["created local tag provider oem1"], False))
        self.assertEqual(hub.created[0]["config"]["profile"]["type"], "STANDARD")

    def test_a_dry_run_changes_nothing(self):
        hub = FakeHub()
        lines, _ = providers.apply_provider(hub, "oem1", dry_run=True)
        self.assertEqual(lines, ["would create local tag provider oem1"])
        self.assertEqual(hub.created, [])

    def test_a_matching_oem_provider_is_left_alone(self):
        hub = FakeHub(existing=providers.provider_body("oem1"))
        self.assertEqual(providers.apply_provider(hub, "oem1"), (["unchanged: local tag provider oem1"], False))

    def test_a_remote_provider_with_an_oem_name_is_reported_as_drift(self):
        existing = providers.provider_body("oem1")
        existing["config"]["profile"]["type"] = "REMOTE"
        lines, drift = providers.apply_provider(FakeHub(existing=existing), "oem1")
        self.assertTrue(drift)
        self.assertIn("type is 'REMOTE', wanted 'STANDARD'", lines[0])


class SiteChoiceTests(unittest.TestCase):
    def test_the_hub_cannot_be_its_own_remote_site_and_an_unknown_site_is_refused(self):
        for bad in ("hub", "nowhere"):
            with self.assertRaises(ValueError):
                providers.check_site(bad)
        providers.check_site("site2")
        providers.check_site("oem4")


if __name__ == "__main__":
    unittest.main()
