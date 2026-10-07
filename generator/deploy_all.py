"""Deploy the repo's projects to every gateway: core and fleet to the hub, core and site to each site gateway (ADR 0014 decision 7).

    python -m generator.deploy_all --dry-run              # show what would happen
    python -m generator.deploy_all                        # create what is missing; stops if a project already exists
    python -m generator.deploy_all --overwrite            # replace every project with the repo's copy
    python -m generator.deploy_all --recreate             # rename existing ones aside (NAME_old) and import fresh copies

A child project runs only when its parent is on the same gateway, so core goes first on each gateway. It is deployed to every
gateway that has a child, because inheritance does not cross the Gateway Network (Phase 2 finding 56). Each project is deployed
as generator.deploy_project does it, including its refusal to overwrite a project whose parent would change.
"""
import argparse
import pathlib
import sys

from generator import deploy_project
from generator.gateway import GATEWAYS, ROOT, GatewayError, RestGateway


def projects_for(gateway):
    """The projects a gateway runs, parent first."""
    return ["core", "fleet"] if gateway == "hub" else ["core", "site"]


def deploy_all(gateways, projects_root, overwrite=False, dry_run=False, recreate=False):
    """gateways: {name: gateway}. Returns the lines to print."""
    lines = []
    for name, gateway in gateways.items():
        lines.append("== %s ==" % name)
        for project in projects_for(name):
            for line in deploy_project.deploy(gateway, pathlib.Path(projects_root) / project, overwrite, dry_run, recreate):
                lines.append("  " + line)
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--overwrite", action="store_true", help="replace projects that exist")
    parser.add_argument("--recreate", action="store_true", help="rename existing projects aside (NAME_old) and import fresh ones")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", action="append", default=[], metavar="GATEWAY", help="limit to this gateway (repeat for more)")
    args = parser.parse_args(argv)
    names = [name for name in GATEWAYS if not args.only or name in args.only]
    try:
        gateways = {name: RestGateway(name) for name in names}
        for line in deploy_all(gateways, pathlib.Path(ROOT) / "projects", args.overwrite, args.dry_run, args.recreate):
            print(line)
        return 0
    except GatewayError as error:
        print("error: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
