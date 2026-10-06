"""Point a site gateway's simulator connections at the host named in the points list (ADR 0013).

    python -m generator.retarget site1 points/site1.csv            # show what would change; change nothing
    python -m generator.retarget site1 points/site1.csv --apply    # make the change

The points list is the source of truth for where the devices are. This changes only the host name (and port) of Modbus
devices that exist and differ from their row, and the host inside the URLs of the OPC UA connection `PlantController` (taken
from the plantcontroller row when there is one, else from the Modbus rows).
Nothing else is touched: not tags, parameters, enabled flags, descriptions, or any other setting. Each update is checked
against the resource's signature, so a change made on the gateway since it was read is refused, not overwritten.
To undo, put the old host back in the points list and run it again.
"""
import argparse
import copy
import sys
import urllib.parse
from dataclasses import dataclass

from generator.gateway import DEVICE_TYPE, OPC_CONNECTION_TYPE, GatewayError, RestGateway
from generator.points import PointsError, read_points

CONNECTION_NAME = "PlantController"


@dataclass
class Change:
    label: str
    resource_type: str
    resource: dict  # the full updated resource, ready to send
    before: str
    after: str


def swap_host(url, host):
    """The same URL with another host name; the port, scheme, and path are kept."""
    parts = urllib.parse.urlsplit(url)
    netloc = host if parts.port is None else "%s:%d" % (host, parts.port)
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def plan(gateway, rows):
    """The changes that make the gateway's existing devices and the plant controller connection match the points list."""
    modbus_rows = [row for row in rows if row.protocol == "modbus"]
    hosts = sorted({row.host for row in modbus_rows})
    if len(hosts) != 1:
        raise GatewayError("the points list names more than one simulator host (%s); retarget needs exactly one" % ", ".join(hosts))
    host = hosts[0]
    opc_rows = [row for row in rows if row.protocol == "opcua"]
    opc_host = opc_rows[0].host if opc_rows else host  # the plant controller row names its own host; otherwise the Modbus one
    changes = []
    for row in modbus_rows:
        existing = gateway.device(row.device)
        if existing is None:
            continue  # generator.apply creates it with the right host
        connectivity = existing["config"]["settings"]["connectivity"]
        if connectivity.get("hostname") != row.host or connectivity.get("port") != row.port:
            updated = copy.deepcopy(existing)
            updated["config"]["settings"]["connectivity"]["hostname"] = row.host
            updated["config"]["settings"]["connectivity"]["port"] = row.port
            changes.append(Change("device %s" % row.device, DEVICE_TYPE, updated,
                                  "%s:%s" % (connectivity.get("hostname"), connectivity.get("port")), "%s:%d" % (row.host, row.port)))
    connection = gateway.opc_connection(CONNECTION_NAME)
    if connection is not None:
        endpoint = connection["config"]["settings"]["endpoint"]
        new_discovery, new_endpoint = swap_host(endpoint["discoveryUrl"], opc_host), swap_host(endpoint["endpointUrl"], opc_host)
        if (new_discovery, new_endpoint) != (endpoint["discoveryUrl"], endpoint["endpointUrl"]):
            updated = copy.deepcopy(connection)
            updated["config"]["settings"]["endpoint"]["discoveryUrl"] = new_discovery
            updated["config"]["settings"]["endpoint"]["endpointUrl"] = new_endpoint
            changes.append(Change("OPC connection %s" % CONNECTION_NAME, OPC_CONNECTION_TYPE, updated,
                                  endpoint["endpointUrl"], new_endpoint))
    return changes


def apply_changes(gateway, changes):
    for change in changes:
        gateway.update_resource(change.resource_type, change.resource)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site")
    parser.add_argument("points", help="path to the points list CSV")
    parser.add_argument("--apply", action="store_true", help="make the changes; without it nothing is changed")
    args = parser.parse_args(argv)
    try:
        rows = [row for row in read_points(args.points) if row.site == args.site]
        gateway = RestGateway(args.site)
        changes = plan(gateway, rows)
        print("== %s ==" % args.site)
        if not changes:
            print("  nothing to change: the gateway already matches the points list")
            return 0
        for change in changes:
            print("  %s %s: %s -> %s" % ("changing" if args.apply else "would change", change.label, change.before, change.after))
        if not args.apply:
            print("  (dry run: add --apply to make these changes)")
            return 0
        apply_changes(gateway, changes)
        healthy = gateway.wait_for_devices()
        print("  done; devices %s" % ("all healthy" if healthy else "NOT all healthy yet (check the gateway; restart a tag that stays Bad)"))
        return 0
    except (PointsError, GatewayError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
