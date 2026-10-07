"""Tests for generator.build: the shapes sent to the gateway."""
import copy
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


PLANT_ROW = DeviceRow("site1", "PlantController", "plantcontroller", None, "sim", 14840, None)
ENCRYPTED = {"type": "Embedded", "data": {"ciphertext": "AAAA", "iv": "BBBB"}}  # what the gateway's encrypt route returns, wrapped
# What the hand-built PlantController connection on site1 held on 2026-10-06, without its gateway-specific encrypted key store
# password (the generator adds one made by the target gateway). Nothing here is secret.
HAND_BUILT_OPC_SETTINGS = {
    "advanced": {
        "acknowledgeTimeout": 5000, "browseOrigin": "OBJECTS_FOLDER", "connectTimeout": 5000,
        "deprecatedDataTypeDictionarySupport": False, "maxArrayLength": 2147483647, "maxMessageSize": 33554432,
        "maxNotificationsPerPublish": 65535, "maxPendingPublishRequests": 2, "maxPerOperation": 8192,
        "maxReferencesPerNode": 8192, "maxStringLength": 2147483647, "requestTimeout": 60000, "sessionTimeout": 120000,
        "timestampSource": "OPC_PREFER_SOURCE",
    },
    "authentication": {"authenticationType": "ANONYMOUS"},
    "configVersion": 2,
    "endpoint": {
        "discoveryUrl": "opc.tcp://sim:14840/fleet-scada/sim", "endpointUrl": "opc.tcp://sim:14840/fleet-scada/sim",
        "hostOverride": "", "securityMode": "None", "securityPolicy": "None",
    },
    "failover": {"discoveryUrl": "", "enabled": False, "endpointUrl": "", "hostOverride": "", "threshold": 3},
    "keepAlive": {"failuresAllowed": 1, "interval": 15000, "timeout": 10000},
    "security": {"certificateValidationEnabled": True, "keyStoreAlias": "client"},
}


OEM_ROW = DeviceRow("oem1", "Inv1", "inverter", 1, "oem1", 15020, 1500.0)


class OemBuildTests(unittest.TestCase):
    """ADR 0015: an OEM site's devices live on the hub, so their device names carry the site; their tags do not."""

    def test_the_device_resource_is_named_with_the_site_and_points_at_the_oem_simulator(self):
        body = build.modbus_device_body(OEM_ROW, FAKE_SCHEMA)
        self.assertEqual(body["name"], "oem1_Inv1")
        self.assertEqual(body["config"]["settings"]["connectivity"]["hostname"], "oem1")

    def test_the_instance_keeps_the_plain_tag_name_and_names_the_prefixed_device(self):
        instance = build.udt_instance(OEM_ROW)
        self.assertEqual(instance["name"], "Inv1")  # so the path below [oem1] matches every other site
        self.assertEqual(build.parameter_values(instance), {"Device": "oem1_Inv1", "UnitId": 1, "RatedKW": 1500.0})

    def test_a_site_gateways_row_is_unchanged(self):
        self.assertEqual(build.modbus_device_body(ROW, FAKE_SCHEMA)["name"], "Inv1")
        self.assertEqual(build.udt_instance(ROW), HAND_BUILT_INV1)


class SiteRatingTests(unittest.TestCase):
    """The nameplate rating is a memory tag, Site/RatedMW, made from the points list for every site, so a fleet view can read
    [<site>]Site/RatedMW whether or not the site has a plant controller."""

    def rows(self, *ratings):
        inverters = [DeviceRow("oem1", "Inv%d" % (n + 1), "inverter", n + 1, "oem1", 15020, kw) for n, kw in enumerate(ratings)]
        return inverters + [DeviceRow("oem1", "Meter", "meter", len(ratings) + 1, "oem1", 15020, None)]

    def test_the_rating_is_the_sum_of_the_inverters_in_megawatts(self):
        self.assertEqual(build.site_rating_mw(self.rows(1500.0, 1500.0, 1500.0)), 4.5)
        self.assertEqual(build.site_rating_mw(self.rows(1250.0, 1250.0, 1250.0, 1250.0)), 5.0)

    def test_a_list_without_inverters_has_no_rating(self):
        self.assertIsNone(build.site_rating_mw([DeviceRow("oem1", "Meter", "meter", 1, "oem1", 15020, None)]))

    def test_the_tag_is_a_float_memory_tag_holding_the_value(self):
        self.assertEqual(build.site_rating_tag(4.5), {"name": "RatedMW", "tagType": "AtomicTag", "valueSource": "memory",
                                                       "dataType": "Float8", "value": 4.5})


class PlantControllerBuildTests(unittest.TestCase):
    def test_a_plant_controller_instance_has_no_parameters_like_the_hand_built_one(self):
        self.assertEqual(build.udt_instance(PLANT_ROW), {"name": "PlantController", "tagType": "UdtInstance", "typeId": "PlantController"})

    def test_the_endpoint_url_comes_from_the_row(self):
        self.assertEqual(build.opc_endpoint_url(PLANT_ROW), "opc.tcp://sim:14840/fleet-scada/sim")
        other = DeviceRow("site2", "PlantController", "plantcontroller", None, "sim2", 14841, None)
        self.assertEqual(build.opc_endpoint_url(other), "opc.tcp://sim2:14841/fleet-scada/sim")

    def test_the_connection_body_matches_the_hand_built_connection(self):
        body = build.opc_connection_body(PLANT_ROW, ENCRYPTED)
        self.assertEqual(body["name"], "PlantController")  # the UDT's members name the connection, so it is fixed
        self.assertEqual((body["collection"], body["enabled"]), ("core", True))
        self.assertEqual(body["config"]["profile"]["type"], "com.inductiveautomation.OpcUaServerType")
        expected = copy.deepcopy(HAND_BUILT_OPC_SETTINGS)
        expected["security"]["keyStoreAliasPassword"] = ENCRYPTED  # the gateway cannot load its client key pair without it
        self.assertEqual(body["config"]["settings"], expected)

    def test_the_connection_body_carries_only_the_encrypted_key_store_password_never_the_plain_one(self):
        # Phase 2 finding 45: without the key store password the connection stays unhealthy ("Unable to retrieve KeyPair").
        text = json.dumps(build.opc_connection_body(PLANT_ROW, ENCRYPTED))
        self.assertNotIn(build.OPC_KEY_STORE_PASSWORD, text)
        for word in ("BEGIN", "PRIVATE", "certificatePem", "privateKeyPem"):
            self.assertNotIn(word, text)

    def test_each_body_is_a_fresh_copy_so_one_site_cannot_change_the_next(self):
        first = build.opc_connection_body(PLANT_ROW, ENCRYPTED)
        first["config"]["settings"]["endpoint"]["endpointUrl"] = "changed"
        first["config"]["settings"]["advanced"]["connectTimeout"] = 1
        first["config"]["settings"]["security"]["keyStoreAliasPassword"]["data"]["ciphertext"] = "changed"
        second = build.opc_connection_body(PLANT_ROW, ENCRYPTED)
        expected = copy.deepcopy(HAND_BUILT_OPC_SETTINGS)
        expected["security"]["keyStoreAliasPassword"] = ENCRYPTED
        self.assertEqual(second["config"]["settings"], expected)
        self.assertEqual(ENCRYPTED["data"]["ciphertext"], "AAAA")


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
