"""Deploy an Ignition project from a folder in the repo to a gateway through the REST API (ADR 0005, ADR 0012).

    python -m generator.deploy_project site1 projects/site --dry-run
    python -m generator.deploy_project site1 projects/site             # create it; refuses if it already exists
    python -m generator.deploy_project site1 projects/site --overwrite # replace it with the repo's copy

The repo folder is the source of truth for a project built as files, so an overwrite replaces whatever is on the gateway,
including edits made in Designer. That is why it needs the flag.
"""
import argparse
import io
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


def deploy(gateway, folder, overwrite=False, dry_run=False):
    """Returns the lines to print."""
    name = pathlib.Path(folder).name
    data = project_zip(folder)
    existing = gateway.project(name)
    count = len(zipfile.ZipFile(io.BytesIO(data)).namelist())
    if existing is not None and not overwrite:
        raise GatewayError("project %s already exists on %s; use --overwrite to replace it with the repo's copy" % (name, gateway.site))
    verb = "would replace" if existing is not None else "would create"
    if dry_run:
        return ["%s project %s (%d files, %d bytes)" % (verb, name, count, len(data))]
    gateway.import_project(name, data, overwrite=existing is not None)
    gateway.scan_projects()
    return ["%s project %s (%d files, %d bytes)" % ("replaced" if existing is not None else "created", name, count, len(data))]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site")
    parser.add_argument("folder", help="the project folder; its name is the project name")
    parser.add_argument("--overwrite", action="store_true", help="replace the project if it exists")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        for line in deploy(RestGateway(args.site), args.folder, args.overwrite, args.dry_run):
            print(line)
        return 0
    except GatewayError as error:
        print("error: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
