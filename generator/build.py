"""Build the gateway objects for one device row: the Modbus device resource and the UDT instance. Pure functions."""


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


def udt_instance(row):
    """A UDT instance in the shape Designer exports: name, type, and the three parameters (ADR 0007)."""
    return {
        "name": row.device,
        "tagType": "UdtInstance",
        "typeId": row.udt,
        "parameters": {
            "Device": {"dataType": "String", "value": row.device},
            "UnitId": {"dataType": "Integer", "value": row.unit_id},
            "RatedKW": {"dataType": "Float", "value": float(row.rated_kw)},
        },
    }


def parameter_values(instance):
    """{parameter name: value} from an exported instance."""
    return {name: spec.get("value") for name, spec in instance.get("parameters", {}).items()}
