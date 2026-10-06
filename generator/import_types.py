"""Put the repo's saved UDT definitions onto a gateway: create the types that are missing, report any that differ.

    python -m generator.import_types site1                    # dry run: report only
    python -m generator.import_types site1 --apply            # create what is missing
    python -m generator.import_types hub --provider oem1 --file gateway/site1/udt-types.json --apply

The definitions come from the file `python -m generator.export_types` saves: UDT definitions live in a gateway's data volume,
so that file is how they survive a `docker compose down -v` (ADR 0005). Nothing is overwritten. A type that already exists is
only compared, and a difference (drift) is reported for a person to decide, because a hand-built type may be the one that is
right. Each missing type is imported on its own with the collision policy Abort, so even a race with someone creating the same
type cannot overwrite it. After an import the types are read back and compared again, because a gateway can store a definition
differently from how it was sent (Phase 1 finding 22).

Exit code 0 means the gateway matches the file, 2 means differences were found, 1 means an error. A saved type that embeds or
extends another type is refused: the tool does not order imports by dependency yet, and none of ours needs it.
"""
import argparse
import json
import pathlib
import sys
from dataclasses import dataclass, field

from generator.gateway import GatewayError, ROOT, RestGateway

TYPES_PATH = "_types_"  # the folder that holds a provider's UDT definitions
MAX_DRIFT_LINES = 40


class TypesError(RuntimeError):
    pass


@dataclass
class Report:
    missing: list = field(default_factory=list)  # in the file, not on the gateway
    created: list = field(default_factory=list)  # of those, the ones this run imported
    unchanged: list = field(default_factory=list)
    drift: list = field(default_factory=list)  # readable lines, one per difference


def parse_types(exported):
    """The UDT type definitions from a saved export (the `_types_` folder). Refuses anything that is not plain types."""
    if exported.get("name") != TYPES_PATH or exported.get("tagType") != "Folder":
        raise TypesError("the file is not an export of the %s folder" % TYPES_PATH)
    types = exported.get("tags", [])
    for node in types:
        if node.get("tagType") != "UdtType":
            raise TypesError("%s is a %s, not a UdtType" % (node.get("name"), node.get("tagType")))
        for trail, type_id in _type_references(node, node["name"]):
            raise TypesError("type %s: %s uses type %r; types that embed or extend another type are not supported yet"
                             % (node["name"], trail, type_id))
    return types


def _type_references(node, trail):
    """(path, typeId) for every member of a type that names another type."""
    for member in node.get("tags", []):
        member_trail = "%s/%s" % (trail, member["name"])
        if member.get("typeId"):
            yield member_trail, member["typeId"]
        yield from _type_references(member, member_trail)


def load_types(path):
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise TypesError("cannot read %s: %s" % (path, error))
    return parse_types(data)


def _short(value):
    if value is None:
        return "absent"
    text = json.dumps(value, sort_keys=True)
    return text if len(text) <= 60 else text[:57] + "..."


def type_drift(wanted, found, trail=None):
    """Differences between a definition in the file and on the gateway, as readable lines. Members are matched by name."""
    trail = trail or wanted["name"]
    problems = []
    for key in sorted((set(wanted) | set(found)) - {"name", "tags", "parameters"}):
        if wanted.get(key) != found.get(key):
            problems.append("%s: %s is %s on the gateway, %s in the file" % (trail, key, _short(found.get(key)), _short(wanted.get(key))))
    want_parameters, found_parameters = wanted.get("parameters", {}), found.get("parameters", {})
    for name in sorted(set(want_parameters) | set(found_parameters)):
        if want_parameters.get(name) != found_parameters.get(name):
            problems.append("%s: parameters.%s is %s on the gateway, %s in the file"
                            % (trail, name, _short(found_parameters.get(name)), _short(want_parameters.get(name))))
    want_members = {m["name"]: m for m in wanted.get("tags", [])}
    found_members = {m["name"]: m for m in found.get("tags", [])}
    for name in sorted(set(want_members) | set(found_members), key=str.lower):
        path = "%s/%s" % (trail, name)
        if name not in found_members:
            problems.append("%s: missing on the gateway" % path)
        elif name not in want_members:
            problems.append("%s: on the gateway but not in the file" % path)
        else:
            problems += type_drift(want_members[name], found_members[name], path)
    return problems


def _types_on(gateway):
    """{type name: definition} for the types a gateway's provider holds. An empty provider answers with tagType Unknown."""
    exported = gateway.export_tags(TYPES_PATH)
    if exported.get("tagType") == "Unknown":
        return {}
    return {node["name"]: node for node in exported.get("tags", [])}


def import_types(gateway, wanted, apply=False):
    report = Report()
    found = _types_on(gateway)
    for node in wanted:
        existing = found.get(node["name"])
        if existing is None:
            report.missing.append(node["name"])
            continue
        problems = type_drift(node, existing)
        report.drift += problems
        if not problems:
            report.unchanged.append(node["name"])
    if apply:
        by_name = {node["name"]: node for node in wanted}
        for name in report.missing:
            try:
                gateway.import_tags({"tags": [by_name[name]]}, path=TYPES_PATH, policy="Abort")
            except GatewayError as error:
                raise GatewayError("importing type %s failed (created before it: %s): %s"
                                   % (name, ", ".join(report.created) or "nothing", error))
            report.created.append(name)
        if report.created:
            after = _types_on(gateway)
            for name in report.created:
                problems = ["%s: missing on the gateway" % name] if name not in after else type_drift(by_name[name], after[name])
                report.drift += ["after import: " + line for line in problems]
    return report


def exit_code(report):
    return 2 if report.drift else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site", help="gateway to import into, for example site1 or hub")
    parser.add_argument("--file", help="saved definitions (default: gateway/<site>/udt-types.json)")
    parser.add_argument("--provider", default="default", help="tag provider to import into (default: default)")
    parser.add_argument("--apply", action="store_true", help="create the missing types; without it nothing is changed")
    args = parser.parse_args(argv)
    path = args.file or pathlib.Path(ROOT) / "gateway" / args.site / "udt-types.json"
    try:
        if not args.file and not pathlib.Path(path).exists():
            raise TypesError("%s has no saved types file of its own; use --file gateway/site1/udt-types.json to give it "
                             "another site's definitions" % args.site)
        wanted = load_types(path)
        report = import_types(RestGateway(args.site, provider=args.provider), wanted, apply=args.apply)
    except (TypesError, GatewayError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    print("== %s [%s] from %s ==" % (args.site, args.provider, path))
    for name in report.missing:
        print("  %s type %s" % ("created" if name in report.created else "would create", name))
    for name in report.unchanged:
        print("  unchanged: type %s" % name)
    for line in report.drift[:MAX_DRIFT_LINES]:
        print("  DRIFT: %s" % line)
    if len(report.drift) > MAX_DRIFT_LINES:
        print("  DRIFT: ... and %d more" % (len(report.drift) - MAX_DRIFT_LINES))
    if report.missing and not args.apply:
        print("  (nothing changed; add --apply to create the missing types)")
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
