"""Deploy an Ignition project from a folder in the repo to a gateway through the REST API (ADR 0005, ADR 0012).

    python -m generator.deploy_project site1 projects/site --dry-run
    python -m generator.deploy_project site1 projects/site             # create it; refuses if it already exists
    python -m generator.deploy_project site1 projects/site --overwrite # replace it with the repo's copy
    python -m generator.deploy_project site1 projects/site --recreate  # rename the current one aside, import a fresh one

The repo folder is the source of truth for a project built as files, so an overwrite replaces whatever is on the gateway,
including edits made in Designer. That is why it needs the flag. A child project (one with a parent, such as site and fleet)
runs only when its parent project is on the same gateway, so deploy the parent first; generator.deploy_all does that for every
gateway.
"""
import argparse
import io
import json
import pathlib
import sys
import zipfile

from generator.gateway import GatewayError, RestGateway


def project_zip(folder):
    """The folder as a project zip: project.json at the root, every other file under its own relative path (LF kept as is)."""
    folder = pathlib.Path(folder)
    if not (folder / "project.json").is_file():
        raise GatewayError("%s has no project.json, so it is not a project folder" % folder)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            archive.write(path, path.relative_to(folder).as_posix())
    return buffer.getvalue()


def project_parent(folder):
    return json.loads((pathlib.Path(folder) / "project.json").read_text(encoding="utf-8")).get("parent", "")


def deploy(gateway, folder, overwrite=False, dry_run=False, recreate=False):
    """Returns the lines to print.

    Overwriting a project whose parent would change is refused: the gateway keeps running the old copy, which cannot see the new
    parent's views (Phase 2 finding 56). --recreate does it safely: the current project is renamed aside (NAME_old) and a fresh
    one is imported under the original name. Nothing is deleted."""
    name = pathlib.Path(folder).name
    data = project_zip(folder)
    existing = gateway.project(name)
    size = "(%d files, %d bytes)" % (len(zipfile.ZipFile(io.BytesIO(data)).namelist()), len(data))
    if existing is not None and recreate:
        aside = name + "_old"
        if gateway.project(aside) is not None:
            raise GatewayError("cannot recreate %s on %s: %s already exists; remove or rename it first" % (name, gateway.site, aside))
        if dry_run:
            return ["would recreate project %s, renaming the current one to %s %s" % (name, aside, size)]
        gateway.rename_project(name, aside)
        gateway.import_project(name, data, overwrite=False)
        gateway.scan_projects()
        return ["recreated project %s %s; the previous one is now %s" % (name, size, aside)]
    if existing is not None and not overwrite:
        raise GatewayError("project %s already exists on %s; use --overwrite to replace it with the repo's copy" % (name, gateway.site))
    if existing is not None and (existing.get("parent") or "") != project_parent(folder):
        raise GatewayError("project %s on %s has parent %r but the repo's has %r: an overwrite would leave the running project "
                           "without its new parent's views; use --recreate" % (name, gateway.site, existing.get("parent") or "", project_parent(folder)))
    if dry_run:
        return ["%s project %s %s" % ("would replace" if existing is not None else "would create", name, size)]
    gateway.import_project(name, data, overwrite=existing is not None)
    gateway.scan_projects()
    return ["%s project %s %s" % ("replaced" if existing is not None else "created", name, size)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site")
    parser.add_argument("folder", help="the project folder; its name is the project name")
    parser.add_argument("--overwrite", action="store_true", help="replace the project if it exists")
    parser.add_argument("--recreate", action="store_true",
                        help="rename an existing project aside (NAME_old) and import a fresh one; needed when its parent changes")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        for line in deploy(RestGateway(args.site), args.folder, args.overwrite, args.dry_run, args.recreate):
            print(line)
        return 0
    except GatewayError as error:
        print("error: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
