"""Save a gateway's UDT definitions into the repo, so a factory reset can be rebuilt from Git (ADR 0005).

    python -m generator.export_types site1      # writes gateway/site1/udt-types.json

UDT definitions live inside the gateway's data volume, not in a project, so without this export `docker compose down -v`
would lose them. The file is written in a stable order (members sorted by name) so Git diffs show real changes only.
"""
import argparse
import json
import pathlib
import sys

from generator.gateway import GatewayError, RestGateway, ROOT


def normalize(node):
    """Copy of exported tag JSON with every list of members sorted by name, for stable diffs."""
    if isinstance(node, dict):
        return {key: normalize(value) for key, value in node.items()}
    if isinstance(node, list):
        items = [normalize(item) for item in node]
        if all(isinstance(item, dict) and "name" in item for item in items):
            items.sort(key=lambda item: item["name"].lower())
        return items
    return node


def render(exported):
    """The text written to the file: sorted keys, two-space indent, LF line endings, one trailing newline."""
    return json.dumps(normalize(exported), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site", help="gateway to export from, for example site1")
    args = parser.parse_args(argv)
    try:
        exported = RestGateway(args.site).export_tags("_types_")
    except GatewayError as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    types = [t["name"] for t in exported.get("tags", [])]
    out = pathlib.Path(ROOT) / "gateway" / args.site / "udt-types.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(exported), encoding="utf-8", newline="\n")
    print("wrote %s with %d types: %s" % (out.relative_to(ROOT), len(types), ", ".join(sorted(types))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
