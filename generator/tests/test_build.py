"""Tests for generator.build: the shapes sent to the gateway."""
import json
import unittest

from generator import build
from generator.points import DeviceRow

ROW = DeviceRow("site1", "Inv1", "inverter", 1, "host.docker.internal", 15020, 1250.0)
FAKE_SCHEMA = {
    "connectivity": {"type": "object", "properties": {
        "hostname": {"type": "string"}, "port": {"type": "number", "default": 502},
        "communicationTimeout": {"type": "number", "default": 2000}}},
    "requestOptimization": {"type": "object", "properties": {"concurrentRequests": {"type": "number", "default": 1}}},
    "advanced": {"type": "object", "properties": {"zeroBasedAddressing": {"type": "boolean", "default": False}}},
}
# What Designer exported for the hand-built Inverters/Inv1 on 2026-10-03.
HAND_BUILT_INV1 = {
    "name": "Inv1",
    "parameters": {
        "Device": {"dataType": "String", "value": "Inv1"},
        "RatedKW": {"dataType": "Float", "value": 1250.0},
        "UnitId": {"dataType": "Integer", "value": 1},
    },
    "tagType": "UdtInstance",
    "typeId": "Inverter",
}


class BuildTests(unittest.TestCase):
    def test_the_generated_instance_matches_the_hand_built_one(self):
        self.assertEqual(build.udt_instance(ROW), HAND_BUILT_INV1)

    def test_parameter_values_reads_an_exported_instance(self):
        self.assertEqual(build.parameter_values(HAND_BUILT_INV1), {"Device": "Inv1", "RatedKW": 1250.0, "UnitId": 1})

    def test_schema_defaults_keep_every_group_and_skip_settings_without_a_default(self):
        defaults = build.schema_defaults(FAKE_SCHEMA)
        self.assertEqual(set(defaults), {"connectivity", "requestOptimization", "advanced"})
        self.assertEqual(defaults["connectivity"], {"port": 502, "communicationTimeout": 2000})

    def test_the_device_body_carries_host_port_and_every_settings_group(self):
        body = build.modbus_device_body(ROW, FAKE_SCHEMA)
        self.assertEqual(body["name"], "Inv1")
        self.assertEqual(body["config"]["profile"], {"type": "ModbusTcp"})
        settings = body["config"]["settings"]
        self.assertEqual(settings["connectivity"]["hostname"], "host.docker.internal")
        self.assertEqual(settings["connectivity"]["port"], 15020)
        self.assertEqual(set(settings), {"connectivity", "requestOptimization", "advanced"})
        self.assertFalse(settings["advanced"]["zeroBasedAddressing"])

    def test_the_unit_id_is_not_part_of_the_device(self):
        body = build.modbus_device_body(DeviceRow("site1", "Inv3", "inverter", 3, "h", 15020, 1250.0), FAKE_SCHEMA)
        self.assertNotIn("unit", json.dumps(body).lower())

    def test_a_weather_station_and_a_meter_get_only_device_and_unit_id(self):
        # The Weather and Meter UDT definitions have no RatedKW parameter (gateway/site1/udt-types.json).
        for name, kind, unit, udt in (("Weather", "weather", 5, "Weather"), ("Meter", "meter", 6, "Meter")):
            instance = build.udt_instance(DeviceRow("site1", name, kind, unit, "h", 15020, None))
            self.assertEqual(instance, {"name": name, "tagType": "UdtInstance", "typeId": udt, "parameters": {
                "Device": {"dataType": "String", "value": name},
                "UnitId": {"dataType": "Integer", "value": unit},
            }})

    def test_rated_power_is_always_a_float(self):
        row = DeviceRow("site1", "Inv2", "inverter", 2, "h", 15020, 1250)
        self.assertIsInstance(build.udt_instance(row)["parameters"]["RatedKW"]["value"], float)


if __name__ == "__main__":
    unittest.main()
