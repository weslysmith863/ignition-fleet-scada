"""Tests for generator.apply against an in-memory fake gateway: create what is missing, never overwrite, report drift."""
import copy
import json
import pathlib
import unittest

from generator import apply, build
from generator.points import read_points
from generator.tests.test_build import FAKE_SCHEMA

ROWS = read_points(pathlib.Path(__file__).resolve().parents[2] / "points" / "site1.csv")
INVERTERS = [row for row in ROWS if row.kind == "inverter"]
OEM = read_points(pathlib.Path(__file__).resolve().parents[2] / "points" / "oem1.csv")
MODBUS = [row for row in ROWS if row.protocol == "modbus"]  # the four inverters, the weather station, and the meter
ENCRYPTED = {"type": "Embedded", "data": {"ciphertext": "AAAA", "iv": "BBBB"}}  # what the gateway's encrypt route returns, wrapped


class FakeGateway:
    def __init__(self):
        self.devices = {}
        self.tags = {}
        self.created_devices = []
        self.imports = []
        self.writes = []  # the order of changes: "device", "wait", "opc", "wait-opc", "instances"
        self.devices_ready = True
        self.opc = {}
        self.created_opc = []
        self.opc_healthy = True
        self.encrypted = []

    def device_settings_schema(self):
        return FAKE_SCHEMA

    def device(self, name):
        return self.devices.get(name)

    def create_device(self, body):
        self.devices[body["name"]] = body
        self.created_devices.append(body["name"])
        self.writes.append("device")

    def wait_for_devices(self, timeout_s=30.0, poll_s=1.0):
        self.writes.append("wait")
        return self.devices_ready

    def encrypt(self, plain_text):
        self.encrypted.append(plain_text)
        return copy.deepcopy(ENCRYPTED)

    def opc_connection(self, name):
        return self.opc.get(name)

    def create_opc_connection(self, body):
        self.opc[body["name"]] = copy.deepcopy(body)
        self.created_opc.append(body["name"])
        self.writes.append("opc")

    def wait_for_healthy(self, resource_type, name, timeout_s=30.0, poll_s=1.0):
        self.writes.append("wait-opc")
        return self.opc_healthy

    def tag(self, path):
        return self.tags.get(path)

    def import_tags(self, payload, path=None, policy="Abort"):
        self.writes.append("instances")
        self.imports.append((path, copy.deepcopy(payload), policy))
        for item in payload["tags"]:
            if path is None and item["tagType"] == "Folder":  # a folder with its children, at the root
                self.tags[item["name"]] = {"name": item["name"], "tagType": "Folder"}
                for child in item["tags"]:
                    self.tags["%s/%s" % (item["name"], child["name"])] = child
            elif path is None:  # an instance directly at the root
                self.tags[item["name"]] = item
            else:
                self.tags["%s/%s" % (path, item["name"])] = item

    def add_hand_built(self, row, device_overrides=None, instance_overrides=None):
        body = build.modbus_device_body(row, FAKE_SCHEMA)
        for key, value in (device_overrides or {}).items():
            body["config"]["settings"]["connectivity"][key] = value
        self.devices[row.device] = body
        instance = build.udt_instance(row)
        for key, value in (instance_overrides or {}).items():
            instance["parameters"][key]["value"] = value
        if row.folder:
            self.tags.setdefault(row.folder, {"name": row.folder, "tagType": "Folder"})
        self.tags[row.tag_path] = instance


class ApplyTests(unittest.TestCase):
    def test_an_empty_gateway_gets_every_device_and_instance_in_one_new_folder(self):
        gateway = FakeGateway()
        report = apply.apply_rows(gateway, INVERTERS)
        self.assertEqual(sorted(gateway.created_devices), ["Inv1", "Inv2", "Inv3", "Inv4"])
        self.assertEqual(len(gateway.imports), 1)
        path, payload, policy = gateway.imports[0]
        self.assertIsNone(path)
        self.assertEqual(policy, "Abort")
        self.assertEqual(payload["tags"][0]["name"], "Inverters")
        self.assertEqual([t["name"] for t in payload["tags"][0]["tags"]], ["Inv1", "Inv2", "Inv3", "Inv4"])
        self.assertEqual(len(report.created_devices), 4)
        self.assertEqual(len(report.created_instances), 4)
        self.assertEqual(report.drift, [])

    def test_hand_built_inv1_and_inv2_are_left_alone_and_only_inv3_and_inv4_are_created(self):
        gateway = FakeGateway()
        gateway.add_hand_built(ROWS[0])
        gateway.add_hand_built(ROWS[1])
        before = copy.deepcopy((gateway.devices, gateway.tags))
        report = apply.apply_rows(gateway, INVERTERS)
        self.assertEqual(gateway.created_devices, ["Inv3", "Inv4"])
        self.assertEqual(len(gateway.imports), 1)
        path, payload, policy = gateway.imports[0]
        self.assertEqual((path, policy), ("Inverters", "Abort"))  # into the existing folder, never overwriting
        self.assertEqual([t["name"] for t in payload["tags"]], ["Inv3", "Inv4"])
        for name in ("Inv1", "Inv2"):
            self.assertEqual(gateway.devices[name], before[0][name])
            self.assertEqual(gateway.tags["Inverters/" + name], before[1]["Inverters/" + name])
        self.assertEqual(sorted(report.unchanged), ["device Inv1", "device Inv2", "instance Inverters/Inv1", "instance Inverters/Inv2"])
        self.assertEqual(report.drift, [])

    def test_devices_are_created_and_healthy_before_the_instances_that_read_them(self):
        # A tag that subscribes before its device is ready can stay stuck on Bad_NodeIdUnknown until it is restarted
        # (Phase 1 finding 26), so every device is created, then waited for, then the instances are imported.
        gateway = FakeGateway()
        report = apply.apply_rows(gateway, INVERTERS)
        self.assertEqual(gateway.writes, ["device"] * 4 + ["wait", "instances"])
        self.assertEqual(report.warnings, [])

    def test_unhealthy_devices_after_the_wait_produce_a_warning_but_the_run_continues(self):
        gateway = FakeGateway()
        gateway.devices_ready = False
        report = apply.apply_rows(gateway, INVERTERS)
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("Restart Tag", report.warnings[0])
        self.assertEqual(len(report.created_instances), 4)

    def test_no_wait_when_no_device_was_created(self):
        gateway = FakeGateway()
        gateway.add_hand_built(ROWS[0])
        apply.apply_rows(gateway, ROWS[:1])
        self.assertEqual(gateway.writes, [])

    def test_a_second_run_changes_nothing(self):
        gateway = FakeGateway()
        apply.apply_rows(gateway, INVERTERS)
        imports_before, devices_before = len(gateway.imports), len(gateway.created_devices)
        report = apply.apply_rows(gateway, INVERTERS)
        self.assertEqual((len(gateway.imports), len(gateway.created_devices)), (imports_before, devices_before))
        self.assertEqual(report.created_devices + report.created_instances + report.drift, [])
        self.assertEqual(len(report.unchanged), 8)

    def test_a_copied_instance_is_reported_as_drift_and_not_fixed(self):
        gateway = FakeGateway()
        gateway.add_hand_built(ROWS[0])
        gateway.add_hand_built(ROWS[1], instance_overrides={"Device": "Inv1", "UnitId": 1})  # Inv2 copied from Inv1
        broken = copy.deepcopy(gateway.tags["Inverters/Inv2"])
        report = apply.apply_rows(gateway, INVERTERS)
        self.assertEqual(len(report.drift), 2)
        self.assertTrue(any("parameter Device is 'Inv1', points list says 'Inv2'" in line for line in report.drift))
        self.assertTrue(any("parameter UnitId is 1, points list says 2" in line for line in report.drift))
        self.assertEqual(gateway.tags["Inverters/Inv2"], broken)  # untouched

    def test_a_device_pointing_at_the_wrong_port_is_reported_as_drift(self):
        gateway = FakeGateway()
        gateway.add_hand_built(ROWS[0], device_overrides={"port": 5020})
        report = apply.apply_rows(gateway, ROWS[:1])
        self.assertEqual(report.drift, ["device Inv1: port is 5020, points list says 15020"])

    def test_a_dry_run_changes_nothing_and_says_what_it_would_do(self):
        gateway = FakeGateway()
        gateway.add_hand_built(ROWS[0])
        report = apply.apply_rows(gateway, INVERTERS, dry_run=True)
        self.assertEqual(gateway.created_devices, [])
        self.assertEqual(gateway.imports, [])
        self.assertEqual(report.created_devices, ["would create device Inv2", "would create device Inv3", "would create device Inv4"])
        self.assertEqual(report.created_instances[0], "would create instance Inverters/Inv2")


class PlantControllerTests(unittest.TestCase):
    """The plant controller row: an OPC UA connection, then its instance at the tag root (no parameters)."""
    EXPECTED_INSTANCE = {"name": "PlantController", "tagType": "UdtInstance", "typeId": "PlantController"}

    def test_the_connection_is_created_after_the_devices_and_healthy_before_the_instances_are_imported(self):
        gateway = FakeGateway()
        report = apply.apply_rows(gateway, ROWS)
        self.assertEqual(gateway.created_opc, ["PlantController"])
        self.assertEqual(gateway.writes, ["device"] * 6 + ["wait", "opc", "wait-opc", "instances", "instances"])
        self.assertEqual(report.created_connections, ["created OPC connection PlantController"])
        self.assertEqual(report.warnings, [])
        self.assertEqual(report.drift, [])

    def test_the_key_store_password_is_encrypted_by_the_gateway_and_only_the_encrypted_value_is_sent(self):
        # Without it the connection stays unhealthy ("Unable to retrieve KeyPair for alias 'client'", Phase 2 finding 45).
        gateway = FakeGateway()
        apply.apply_rows(gateway, ROWS)
        self.assertEqual(gateway.encrypted, [build.OPC_KEY_STORE_PASSWORD])
        stored = gateway.opc["PlantController"]["config"]["settings"]["security"]
        self.assertEqual(stored["keyStoreAliasPassword"], ENCRYPTED)
        self.assertNotIn(build.OPC_KEY_STORE_PASSWORD, json.dumps(gateway.opc))

    def test_nothing_is_encrypted_on_a_dry_run_or_when_the_connection_already_exists(self):
        dry = FakeGateway()
        apply.apply_rows(dry, ROWS, dry_run=True)
        self.assertEqual(dry.encrypted, [])
        gateway = FakeGateway()
        apply.apply_rows(gateway, ROWS)
        gateway.encrypted.clear()
        apply.apply_rows(gateway, ROWS)
        self.assertEqual(gateway.encrypted, [])

    def test_the_encrypted_password_is_not_compared_so_it_never_shows_as_drift(self):
        gateway = FakeGateway()
        apply.apply_rows(gateway, ROWS)
        gateway.opc["PlantController"]["config"]["settings"]["security"]["keyStoreAliasPassword"] = {"type": "Embedded", "data": {"x": 1}}
        self.assertEqual(apply.apply_rows(gateway, ROWS).drift, [])

    def test_the_instance_goes_in_with_the_other_root_instances_and_has_no_parameters(self):
        gateway = FakeGateway()
        apply.apply_rows(gateway, ROWS)
        _, root_payload, policy = gateway.imports[-1]
        self.assertEqual(policy, "Abort")
        self.assertEqual([t["name"] for t in root_payload["tags"]], ["Weather", "Meter", "PlantController"])
        self.assertEqual(root_payload["tags"][2], self.EXPECTED_INSTANCE)

    def test_an_existing_matching_connection_and_instance_are_left_alone(self):
        gateway = FakeGateway()
        apply.apply_rows(gateway, ROWS)
        connection, instance = copy.deepcopy(gateway.opc), copy.deepcopy(gateway.tags["PlantController"])
        report = apply.apply_rows(gateway, ROWS)
        self.assertEqual(len(gateway.created_opc), 1)  # not created again
        self.assertEqual((gateway.opc, gateway.tags["PlantController"]), (connection, instance))
        self.assertIn("OPC connection PlantController", report.unchanged)
        self.assertIn("instance PlantController", report.unchanged)
        self.assertEqual(report.created_connections + report.created_instances + report.drift, [])

    def test_a_connection_pointing_somewhere_else_is_reported_as_drift_and_not_fixed(self):
        gateway = FakeGateway()
        apply.apply_rows(gateway, ROWS)
        gateway.opc["PlantController"]["config"]["settings"]["endpoint"]["endpointUrl"] = "opc.tcp://old:14840/fleet-scada/sim"
        broken = copy.deepcopy(gateway.opc)
        report = apply.apply_rows(gateway, ROWS)
        self.assertEqual(report.drift, ["OPC connection PlantController: endpointUrl is 'opc.tcp://old:14840/fleet-scada/sim', "
                                        "points list says 'opc.tcp://sim:14840/fleet-scada/sim'"])
        self.assertEqual(gateway.opc, broken)  # untouched

    def test_a_connection_with_security_turned_on_is_reported_as_drift(self):
        gateway = FakeGateway()
        apply.apply_rows(gateway, ROWS)
        gateway.opc["PlantController"]["config"]["settings"]["endpoint"]["securityMode"] = "SignAndEncrypt"
        report = apply.apply_rows(gateway, ROWS)
        self.assertEqual(report.drift, ["OPC connection PlantController: securityMode is 'SignAndEncrypt', points list says 'None'"])

    def test_an_unhealthy_connection_after_the_wait_produces_a_warning_but_the_run_continues(self):
        gateway = FakeGateway()
        gateway.opc_healthy = False
        report = apply.apply_rows(gateway, ROWS)
        self.assertTrue(any("PlantController connection" in w and "Restart Tag" in w for w in report.warnings), report.warnings)
        self.assertIn("created instance PlantController", report.created_instances)

    def test_a_dry_run_creates_nothing_and_says_what_it_would_do(self):
        gateway = FakeGateway()
        report = apply.apply_rows(gateway, ROWS, dry_run=True)
        self.assertEqual((gateway.created_opc, gateway.writes), ([], []))
        self.assertEqual(report.created_connections, ["would create OPC connection PlantController"])
        self.assertIn("would create instance PlantController", report.created_instances)

    def test_a_list_without_a_plant_controller_never_touches_opc(self):
        gateway = FakeGateway()
        apply.apply_rows(gateway, MODBUS)
        self.assertEqual(gateway.created_opc, [])
        self.assertNotIn("opc", gateway.writes)
        self.assertNotIn("wait-opc", gateway.writes)

    def test_no_wait_when_the_connection_exists_and_only_the_instance_is_missing(self):
        gateway = FakeGateway()
        apply.apply_rows(gateway, ROWS)
        del gateway.tags["PlantController"]
        gateway.writes.clear()
        apply.apply_rows(gateway, ROWS)
        self.assertEqual(gateway.writes, ["instances"])


class OemSiteTests(unittest.TestCase):
    """oem1 is read by the hub: Modbus devices named with the site, plain tag names, no OPC connection (ADR 0015)."""

    def test_the_devices_carry_the_site_and_the_instances_keep_plain_names_with_the_prefixed_device_as_a_parameter(self):
        gateway = FakeGateway()
        report = apply.apply_rows(gateway, OEM)
        self.assertEqual(sorted(gateway.created_devices), ["oem1_Inv1", "oem1_Inv2", "oem1_Inv3", "oem1_Meter", "oem1_Weather"])
        folder_payload = gateway.imports[0][1]["tags"][0]
        self.assertEqual([t["name"] for t in folder_payload["tags"]], ["Inv1", "Inv2", "Inv3"])
        self.assertEqual(build.parameter_values(folder_payload["tags"][1])["Device"], "oem1_Inv2")
        root = gateway.imports[1][1]["tags"]
        self.assertEqual([(t["name"], build.parameter_values(t)["Device"]) for t in root],
                         [("Weather", "oem1_Weather"), ("Meter", "oem1_Meter")])
        self.assertEqual((gateway.created_opc, report.drift), ([], []))

    def test_a_second_run_changes_nothing_and_finds_no_drift(self):
        gateway = FakeGateway()
        apply.apply_rows(gateway, OEM)
        imports = len(gateway.imports)
        report = apply.apply_rows(gateway, OEM)
        self.assertEqual((len(gateway.imports), report.drift), (imports, []))
        self.assertEqual(len(report.unchanged), 10)  # five devices and five instances

    def test_a_device_with_the_site_less_name_is_not_mistaken_for_the_oem_one(self):
        gateway = FakeGateway()
        gateway.add_hand_built(INVERTERS[0])  # a site gateway's own Inv1 must not satisfy oem1's Inv1
        apply.apply_rows(gateway, OEM)
        self.assertIn("oem1_Inv1", gateway.created_devices)


class SiteRatingTagTests(unittest.TestCase):
    def test_the_tag_is_created_in_a_new_site_folder_with_the_rating_from_the_points_list(self):
        gateway = FakeGateway()
        lines, drift = apply.apply_site_rating(gateway, OEM)
        self.assertEqual((lines, drift), (["created tag Site/RatedMW (4.5 MW)"], False))
        path, payload, policy = gateway.imports[0]
        self.assertEqual((path, policy), (None, "Abort"))
        self.assertEqual(payload["tags"][0]["name"], "Site")
        self.assertEqual(payload["tags"][0]["tags"][0]["value"], 4.5)

    def test_an_existing_matching_tag_is_left_alone(self):
        gateway = FakeGateway()
        apply.apply_site_rating(gateway, OEM)
        gateway.imports.clear()
        lines, drift = apply.apply_site_rating(gateway, OEM)
        self.assertEqual((lines, drift, gateway.imports), (["unchanged: tag Site/RatedMW"], False, []))

    def test_a_different_value_is_reported_as_drift_and_not_fixed(self):
        gateway = FakeGateway()
        apply.apply_site_rating(gateway, OEM)
        gateway.tags["Site/RatedMW"]["value"] = 9.0
        lines, drift = apply.apply_site_rating(gateway, OEM)
        self.assertTrue(drift)
        self.assertEqual(lines, ["DRIFT: tag Site/RatedMW: value is 9.0, points list says 4.5"])
        self.assertEqual(gateway.tags["Site/RatedMW"]["value"], 9.0)

    def test_a_dry_run_changes_nothing(self):
        gateway = FakeGateway()
        lines, _ = apply.apply_site_rating(gateway, OEM, dry_run=True)
        self.assertEqual(lines, ["would create tag Site/RatedMW (4.5 MW)"])
        self.assertEqual(gateway.imports, [])

    def test_a_list_without_inverters_has_nothing_to_do(self):
        lines, drift = apply.apply_site_rating(FakeGateway(), [row for row in OEM if row.kind == "meter"])
        self.assertEqual((lines, drift), ([], False))

    def test_the_site_gateways_get_it_too(self):
        lines, _ = apply.apply_site_rating(FakeGateway(), ROWS)
        self.assertEqual(lines, ["created tag Site/RatedMW (5.0 MW)"])


class WeatherAndMeterTests(unittest.TestCase):
    def test_the_full_list_creates_six_devices_then_the_inverter_folder_then_two_root_instances(self):
        gateway = FakeGateway()
        report = apply.apply_rows(gateway, MODBUS)
        self.assertEqual(sorted(gateway.created_devices), ["Inv1", "Inv2", "Inv3", "Inv4", "Meter", "Weather"])
        self.assertEqual(gateway.writes, ["device"] * 6 + ["wait", "instances", "instances"])
        (folder_path, folder_payload, _), (root_path, root_payload, root_policy) = gateway.imports
        self.assertIsNone(folder_path)
        self.assertEqual(folder_payload["tags"][0]["name"], "Inverters")
        self.assertIsNone(root_path)  # the root, not a folder
        self.assertEqual(root_policy, "Abort")
        self.assertEqual([t["name"] for t in root_payload["tags"]], ["Weather", "Meter"])
        self.assertEqual([t["typeId"] for t in root_payload["tags"]], ["Weather", "Meter"])
        self.assertEqual(report.created_instances[-2:], ["created instance Weather", "created instance Meter"])
        self.assertEqual(report.drift, [])

    def test_only_weather_and_meter_are_created_when_the_inverters_already_exist(self):
        gateway = FakeGateway()
        for row in INVERTERS:
            gateway.add_hand_built(row)
        before = copy.deepcopy((gateway.devices, gateway.tags))
        apply.apply_rows(gateway, MODBUS)
        self.assertEqual(sorted(gateway.created_devices), ["Meter", "Weather"])
        self.assertEqual(len(gateway.imports), 1)
        for name, device in before[0].items():
            self.assertEqual(gateway.devices[name], device)
        for path, tag in before[1].items():
            self.assertEqual(gateway.tags[path], tag)

    def test_a_weather_instance_on_the_wrong_unit_is_reported_as_drift_and_not_fixed(self):
        gateway = FakeGateway()
        weather = next(row for row in ROWS if row.device == "Weather")
        gateway.add_hand_built(weather, instance_overrides={"UnitId": 1})
        broken = copy.deepcopy(gateway.tags["Weather"])
        report = apply.apply_rows(gateway, [weather])
        self.assertEqual(report.drift, ["instance Weather: parameter UnitId is 1, points list says 5"])
        self.assertEqual(gateway.tags["Weather"], broken)

    def test_a_second_run_over_the_full_list_changes_nothing(self):
        gateway = FakeGateway()
        apply.apply_rows(gateway, MODBUS)
        imports_before = len(gateway.imports)
        report = apply.apply_rows(gateway, MODBUS)
        self.assertEqual(len(gateway.imports), imports_before)
        self.assertEqual(report.created_devices + report.created_instances + report.drift, [])
        self.assertEqual(len(report.unchanged), 12)


if __name__ == "__main__":
    unittest.main()
