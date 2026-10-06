"""Tests for generator.retarget: only host names move, nothing is changed without --apply, and nothing is overwritten blindly."""
import copy
import unittest

from generator import build, retarget
from generator.gateway import GatewayError
from generator.points import DeviceRow
from generator.tests.test_build import FAKE_SCHEMA

OLD, NEW = "host.docker.internal", "sim"
ROWS = [DeviceRow("site1", "Inv%d" % n, "inverter", n, NEW, 15020, 1250.0) for n in (1, 2)] + [
    DeviceRow("site1", "Weather", "weather", 5, NEW, 15020, None)]
CONNECTION = {
    "name": "PlantController", "collection": "core", "enabled": True, "description": "", "signature": "abc",
    "type": "ignition/opc-connection", "metrics": {"x": 1}, "healthchecks": {},
    "config": {"profile": {"type": "com.inductiveautomation.OpcUaServerType"}, "settings": {
        "endpoint": {"discoveryUrl": "opc.tcp://%s:14840/fleet-scada/sim" % OLD, "endpointUrl": "opc.tcp://%s:14840/fleet-scada/sim" % OLD,
                     "securityPolicy": "None", "securityMode": "None", "hostOverride": ""},
        "authentication": {"authenticationType": "ANONYMOUS"}}},
}


def device_at(row, host):
    body = build.modbus_device_body(DeviceRow(row.site, row.device, row.kind, row.unit_id, host, row.port, row.rated_kw), FAKE_SCHEMA)
    body["signature"] = "sig-" + row.device
    return body


class FakeGateway:
    site = "site1"

    def __init__(self, devices, connection=None):
        self.devices = {d["name"]: d for d in devices}
        self.connection = connection
        self.updates = []

    def device(self, name):
        return self.devices.get(name)

    def opc_connection(self, name):
        return self.connection

    def update_resource(self, resource_type, resource):
        self.updates.append((resource_type, copy.deepcopy(resource)))


PLANT = DeviceRow("site1", "PlantController", "plantcontroller", None, NEW, 14840, None)


class PlantControllerRowTests(unittest.TestCase):
    """The plant controller row names the OPC UA host; it is not a Modbus device and is never looked up as one."""

    def test_a_plant_controller_row_is_not_treated_as_a_modbus_device(self):
        stray = device_at(DeviceRow("site1", "PlantController", "meter", 9, OLD, 15020, None), OLD)  # a Modbus device that shares the name
        gateway = FakeGateway([device_at(r, NEW) for r in ROWS] + [stray], None)
        self.assertEqual(retarget.plan(gateway, ROWS + [PLANT]), [])

    def test_the_connection_host_comes_from_the_plant_controller_row(self):
        gateway = FakeGateway([device_at(r, NEW) for r in ROWS], CONNECTION)
        other = DeviceRow("site1", "PlantController", "plantcontroller", None, "elsewhere", 14840, None)
        changes = retarget.plan(gateway, ROWS + [other])
        self.assertEqual([c.label for c in changes], ["OPC connection PlantController"])  # the Modbus devices stay on sim
        self.assertEqual(changes[0].after, "opc.tcp://elsewhere:14840/fleet-scada/sim")

    def test_with_a_plant_controller_row_the_connection_still_follows_the_simulator_host(self):
        gateway = FakeGateway([device_at(r, NEW) for r in ROWS], CONNECTION)
        changes = retarget.plan(gateway, ROWS + [PLANT])
        self.assertEqual([c.after for c in changes], ["opc.tcp://sim:14840/fleet-scada/sim"])


class SwapHostTests(unittest.TestCase):
    def test_only_the_host_changes_and_the_port_and_path_are_kept(self):
        self.assertEqual(retarget.swap_host("opc.tcp://host.docker.internal:14840/fleet-scada/sim", "sim"), "opc.tcp://sim:14840/fleet-scada/sim")


class PlanTests(unittest.TestCase):
    def test_devices_and_the_connection_that_point_elsewhere_are_planned(self):
        gateway = FakeGateway([device_at(r, OLD) for r in ROWS], CONNECTION)
        changes = retarget.plan(gateway, ROWS)
        self.assertEqual([c.label for c in changes], ["device Inv1", "device Inv2", "device Weather", "OPC connection PlantController"])
        self.assertEqual(changes[0].before, "host.docker.internal:15020")
        self.assertEqual(changes[0].after, "sim:15020")
        self.assertEqual(changes[3].after, "opc.tcp://sim:14840/fleet-scada/sim")

    def test_nothing_is_planned_when_the_gateway_already_matches(self):
        updated = copy.deepcopy(CONNECTION)
        updated["config"]["settings"]["endpoint"]["discoveryUrl"] = "opc.tcp://sim:14840/fleet-scada/sim"
        updated["config"]["settings"]["endpoint"]["endpointUrl"] = "opc.tcp://sim:14840/fleet-scada/sim"
        self.assertEqual(retarget.plan(FakeGateway([device_at(r, NEW) for r in ROWS], updated), ROWS), [])

    def test_a_device_that_does_not_exist_yet_is_left_to_apply(self):
        gateway = FakeGateway([device_at(ROWS[0], OLD)])
        self.assertEqual([c.label for c in retarget.plan(gateway, ROWS)], ["device Inv1"])

    def test_the_planned_resources_differ_from_the_originals_only_in_the_host_fields(self):
        gateway = FakeGateway([device_at(r, OLD) for r in ROWS], CONNECTION)
        for change in retarget.plan(gateway, ROWS):
            original = copy.deepcopy(gateway.devices.get(change.label.split()[-1]) or CONNECTION)
            if change.label.startswith("device"):
                original["config"]["settings"]["connectivity"]["hostname"] = NEW
            else:
                original["config"]["settings"]["endpoint"]["discoveryUrl"] = "opc.tcp://sim:14840/fleet-scada/sim"
                original["config"]["settings"]["endpoint"]["endpointUrl"] = "opc.tcp://sim:14840/fleet-scada/sim"
            self.assertEqual(change.resource, original, change.label)

    def test_more_than_one_simulator_host_is_refused(self):
        rows = [ROWS[0], DeviceRow("site1", "Inv2", "inverter", 2, "other", 15020, 1250.0)]
        with self.assertRaisesRegex(GatewayError, "more than one simulator host"):
            retarget.plan(FakeGateway([]), rows)


class ApplyTests(unittest.TestCase):
    def test_apply_sends_each_change_with_its_resource_type_and_the_original_signature(self):
        gateway = FakeGateway([device_at(r, OLD) for r in ROWS], CONNECTION)
        retarget.apply_changes(gateway, retarget.plan(gateway, ROWS))
        self.assertEqual(len(gateway.updates), 4)
        self.assertEqual([t for t, _ in gateway.updates], [retarget.DEVICE_TYPE] * 3 + [retarget.OPC_CONNECTION_TYPE])
        self.assertEqual(gateway.updates[0][1]["signature"], "sig-Inv1")
        self.assertEqual(gateway.updates[3][1]["signature"], "abc")


if __name__ == "__main__":
    unittest.main()
