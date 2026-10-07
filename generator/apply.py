"""Make a gateway match the points list: create the devices, OPC connection, and UDT instances that are missing, report any that differ.

    python -m generator.apply points/site1.csv --dry-run   # show what would happen
    python -m generator.apply points/site1.csv             # create what is missing

It never overwrites or deletes anything: existing devices, connections, and instances are only compared. A difference (drift)
is reported and left for a person to decide, because a hand-built object may be the one that is right. Exit code 0 means the
gateway matches the points list, 2 means differences were found, 1 means an error.

Modbus rows (inverter, weather, meter) become a Modbus device and an instance. A plantcontroller row becomes the OPC UA
connection `PlantController` and an instance of the PlantController UDT. The UDT definitions themselves come first, from
`python -m generator.import_types`.
"""
import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field

from generator import build, sites
from generator.gateway import OPC_CONNECTION_TYPE, GatewayError, RestGateway
from generator.points import PointsError, read_points


@dataclass
class Report:
    created_devices: list = field(default_factory=list)
    created_connections: list = field(default_factory=list)
    created_instances: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    drift: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def device_drift(row, existing):
    """Differences between the points list and an existing device resource."""
    config = existing.get("config", {})
    connectivity = config.get("settings", {}).get("connectivity", {})
    found = {"type": config.get("profile", {}).get("type"), "host": connectivity.get("hostname"),
             "port": connectivity.get("port"), "enabled": existing.get("enabled")}
    wanted = {"type": "ModbusTcp", "host": row.host, "port": row.port, "enabled": True}
    return ["device %s: %s is %r, points list says %r" % (row.resource_name, key, found[key], wanted[key])
            for key in wanted if found[key] != wanted[key]]


def connection_drift(row, existing):
    """Differences between the points list and an existing OPC UA connection: where it points and whether security is off."""
    wanted_body = build.opc_connection_body(row, None)  # the encrypted key store password is not compared
    wanted = dict(wanted_body["config"]["settings"]["endpoint"], enabled=True)
    endpoint = existing.get("config", {}).get("settings", {}).get("endpoint", {})
    found = dict(endpoint, enabled=existing.get("enabled"))
    return ["OPC connection %s: %s is %r, points list says %r" % (build.OPC_CONNECTION_NAME, key, found.get(key), wanted[key])
            for key in ("endpointUrl", "discoveryUrl", "securityPolicy", "securityMode", "enabled") if found.get(key) != wanted[key]]


def instance_drift(row, existing):
    """Differences between the points list and an existing UDT instance."""
    wanted = build.udt_instance(row)
    problems = []
    if existing.get("typeId") != wanted["typeId"]:
        problems.append("instance %s: type is %r, points list says %r" % (row.device, existing.get("typeId"), wanted["typeId"]))
    found_values = build.parameter_values(existing)
    for name, expected in build.parameter_values(wanted).items():
        if found_values.get(name) != expected:
            problems.append("instance %s: parameter %s is %r, points list says %r" % (row.device, name, found_values.get(name), expected))
    return problems


def apply_rows(gateway, rows, dry_run=False):
    report = Report()
    missing_devices, missing_connections, missing_instances = [], [], defaultdict(list)
    for row in rows:
        if row.protocol == "modbus":
            existing = gateway.device(row.resource_name)
            if existing is None:
                missing_devices.append(row)
            else:
                _record(report, "device %s" % row.resource_name, device_drift(row, existing))
        else:
            existing = gateway.opc_connection(build.OPC_CONNECTION_NAME)
            if existing is None:
                missing_connections.append(row)
            else:
                _record(report, "OPC connection %s" % build.OPC_CONNECTION_NAME, connection_drift(row, existing))
    for row in rows:
        existing = gateway.tag(row.tag_path)
        if existing is None:
            missing_instances[row.folder].append(row)
        else:
            _record(report, "instance %s" % row.tag_path, instance_drift(row, existing))

    verb = "would create" if dry_run else "created"
    if missing_devices and not dry_run:
        schema = gateway.device_settings_schema()
        for row in missing_devices:
            gateway.create_device(build.modbus_device_body(row, schema))
        if missing_instances and not gateway.wait_for_devices():
            report.warnings.append("devices were not all healthy after waiting; if new instance tags show "
                                   "Bad_NodeIdUnknown, use Restart Tag on them (finding 26)")
    if missing_connections and not dry_run:
        encrypted_key_store = gateway.encrypt(build.OPC_KEY_STORE_PASSWORD)  # made by this gateway, for this gateway only
        for row in missing_connections:
            gateway.create_opc_connection(build.opc_connection_body(row, encrypted_key_store))
        if missing_instances and not gateway.wait_for_healthy(OPC_CONNECTION_TYPE, build.OPC_CONNECTION_NAME):
            report.warnings.append("the %s connection was not healthy after waiting; if its instance tags show "
                                   "Bad_NodeIdUnknown, use Restart Tag on them (finding 26)" % build.OPC_CONNECTION_NAME)
    report.created_devices = ["%s device %s" % (verb, row.resource_name) for row in missing_devices]
    report.created_connections = ["%s OPC connection %s" % (verb, build.OPC_CONNECTION_NAME) for _ in missing_connections]
    for folder, folder_rows in missing_instances.items():
        if not dry_run:
            instances = [build.udt_instance(r) for r in folder_rows]
            if not folder:  # instances at the tag root (Weather, Meter, PlantController): no folder to create
                gateway.import_tags({"tags": instances})
            elif gateway.tag(folder) is None:  # a fresh gateway: create the folder together with its instances
                gateway.import_tags({"tags": [{"name": folder, "tagType": "Folder", "tags": instances}]})
            else:
                gateway.import_tags({"tags": instances}, path=folder)
        report.created_instances += ["%s instance %s" % (verb, r.tag_path) for r in folder_rows]
    return report


def apply_site_rating(gateway, rows, dry_run=False):
    """The nameplate rating tag Site/RatedMW, from the points list (ADR 0015). Created if missing, otherwise only compared."""
    rated_mw = build.site_rating_mw(rows)
    if rated_mw is None:
        return [], False
    existing = gateway.tag("Site/RatedMW")
    if existing is not None:
        if existing.get("value") != rated_mw:
            return ["DRIFT: tag Site/RatedMW: value is %r, points list says %r" % (existing.get("value"), rated_mw)], True
        return ["unchanged: tag Site/RatedMW"], False
    line = "tag Site/RatedMW (%s MW)" % rated_mw
    if dry_run:
        return ["would create " + line], False
    tag = build.site_rating_tag(rated_mw)
    if gateway.tag("Site") is None:
        gateway.import_tags({"tags": [{"name": "Site", "tagType": "Folder", "tags": [tag]}]})
    else:
        gateway.import_tags({"tags": [tag]}, path="Site")
    return ["created " + line], False


def _record(report, label, problems):
    if problems:
        report.drift += problems
    else:
        report.unchanged.append(label)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("points", help="path to the points list CSV")
    parser.add_argument("--dry-run", action="store_true", help="report only; change nothing")
    args = parser.parse_args(argv)
    try:
        rows = read_points(args.points)
        by_site = defaultdict(list)
        for row in rows:
            by_site[row.site].append(row)
        exit_code = 0
        for site, site_rows in by_site.items():
            gateway = RestGateway(sites.gateway_for(site), provider=sites.provider_for(site))
            report = apply_rows(gateway, site_rows, dry_run=args.dry_run)
            rating_lines, rating_drift = apply_site_rating(gateway, site_rows, dry_run=args.dry_run)
            print("== %s ==" % site)
            for line in report.created_devices + report.created_connections + report.created_instances:
                print("  %s" % line)
            for line in report.unchanged:
                print("  unchanged: %s" % line)
            for line in report.drift:
                print("  DRIFT: %s" % line)
            for line in report.warnings:
                print("  WARNING: %s" % line)
            for line in rating_lines:
                print("  %s" % line)
            if report.drift or rating_drift:
                exit_code = 2
        return exit_code
    except (PointsError, GatewayError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
