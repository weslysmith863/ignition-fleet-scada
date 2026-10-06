"""Build the gateway objects for one device row: the Modbus device resource, the OPC UA connection, and the UDT instance.

Pure functions."""
import copy

# The plant controller's OPC UA connection. The PlantController UDT's members name their OPC server `PlantController`, so the
# connection must always have that name (ADR 0010). The path is the one the simulator serves.
OPC_CONNECTION_NAME = "PlantController"
OPC_ENDPOINT_PATH = "/fleet-scada/sim"
OPC_PROFILE_TYPE = "com.inductiveautomation.OpcUaServerType"
# The password of the gateway's OPC UA client key store, alias `client`. The connection stays unhealthy without it, even with
# security off ("Unable to retrieve KeyPair for alias 'client'", Phase 2 finding 45). Ignition's OPC UA documentation pages
# (8.1 and 8.3) do not state a default; this one came from a web search and was confirmed on the 8.3.9 hub on 2026-10-06. It is
# a dev default for a self-generated client certificate, not a credential for anything else, and it only ever leaves this file
# encrypted by the target gateway (`gateway.encrypt`): the gateway's own ciphertext is never copied between gateways.
OPC_KEY_STORE_PASSWORD = "password"  # check-secrets: allow password-literal - dev default for a self-generated client key store (finding 45)
# What the hand-built connection on site1 held on 2026-10-06, apart from its endpoint and its key store password (added by
# opc_connection_body, encrypted). The REST API gives no defaults for this connection type, so the groups are listed in full.
# Security is off (ADR 0010).
OPC_SETTINGS = {
    "advanced": {
        "acknowledgeTimeout": 5000, "browseOrigin": "OBJECTS_FOLDER", "connectTimeout": 5000,
        "deprecatedDataTypeDictionarySupport": False, "maxArrayLength": 2147483647, "maxMessageSize": 33554432,
        "maxNotificationsPerPublish": 65535, "maxPendingPublishRequests": 2, "maxPerOperation": 8192,
        "maxReferencesPerNode": 8192, "maxStringLength": 2147483647, "requestTimeout": 60000, "sessionTimeout": 120000,
        "timestampSource": "OPC_PREFER_SOURCE",
    },
    "authentication": {"authenticationType": "ANONYMOUS"},
    "configVersion": 2,
    "endpoint": {"discoveryUrl": "", "endpointUrl": "", "hostOverride": "", "securityMode": "None", "securityPolicy": "None"},
    "failover": {"discoveryUrl": "", "enabled": False, "endpointUrl": "", "hostOverride": "", "threshold": 3},
    "keepAlive": {"failuresAllowed": 1, "interval": 15000, "timeout": 10000},
    "security": {"certificateValidationEnabled": True, "keyStoreAlias": "client"},
}


def schema_defaults(properties):
    """Nested defaults from a device settings schema. The device resource needs every settings group (Phase 1 finding 14)."""
    out = {}
    for name, spec in properties.items():
        if spec.get("type") == "object" and "properties" in spec:
            out[name] = schema_defaults(spec["properties"])
        elif spec.get("default") is not None:
            out[name] = spec["default"]
    return out


def modbus_device_body(row, settings_schema):
    """Body for POST /resources/com.inductiveautomation.opcua/device: a Modbus TCP device at the row's host and port.

    The unit ID is deliberately not here: in Ignition it is part of each tag address (Phase 1 finding 13)."""
    settings = schema_defaults(settings_schema)
    settings["connectivity"]["hostname"] = row.host
    settings["connectivity"]["port"] = row.port
    return {
        "name": row.device,
        "collection": "core",
        "enabled": True,
        "description": "Generated from the points list",
        "config": {"profile": {"type": "ModbusTcp"}, "settings": settings},
    }


def opc_endpoint_url(row):
    """The OPC UA endpoint of a plant controller row: its host and port, and the path the simulator serves."""
    return "opc.tcp://%s:%d%s" % (row.host, row.port, OPC_ENDPOINT_PATH)


def opc_connection_body(row, key_store_password):
    """Body for POST /resources/ignition/opc-connection: an anonymous connection with no security to the row's endpoint.

    `key_store_password` is OPC_KEY_STORE_PASSWORD after the target gateway's encrypt route has wrapped it."""
    settings = copy.deepcopy(OPC_SETTINGS)
    settings["endpoint"]["endpointUrl"] = opc_endpoint_url(row)
    settings["endpoint"]["discoveryUrl"] = opc_endpoint_url(row)
    settings["security"]["keyStoreAliasPassword"] = copy.deepcopy(key_store_password)
    return {
        "name": OPC_CONNECTION_NAME,
        "collection": "core",
        "enabled": True,
        "description": "Generated from the points list",
        "config": {"profile": {"type": OPC_PROFILE_TYPE, "readOnly": False}, "settings": settings},
    }


def udt_instance(row):
    """A UDT instance in the shape Designer exports: name, type, and its parameters (ADR 0007). Device and UnitId for
    every Modbus kind; RatedKW only for an inverter, because the Weather and Meter types do not have it. The PlantController
    type has no parameters at all."""
    if row.protocol == "opcua":
        return {"name": row.device, "tagType": "UdtInstance", "typeId": row.udt}
    parameters = {
        "Device": {"dataType": "String", "value": row.device},
        "UnitId": {"dataType": "Integer", "value": row.unit_id},
    }
    if row.rated_kw is not None:
        parameters["RatedKW"] = {"dataType": "Float", "value": float(row.rated_kw)}
    return {"name": row.device, "tagType": "UdtInstance", "typeId": row.udt, "parameters": parameters}


def parameter_values(instance):
    """{parameter name: value} from an exported instance."""
    return {name: spec.get("value") for name, spec in instance.get("parameters", {}).items()}
