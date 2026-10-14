"""Apply the repo's sql/ files to the PostgreSQL container, in order (ADR 0018, 0020, 0021).

    python -m generator.sqlfiles            # dry run: list the files and the command each one goes through
    python -m generator.sqlfiles --apply    # run them

Every file is written to be run more than once (IF NOT EXISTS, OR REPLACE or DROP IF EXISTS, ON CONFLICT), so applying all of
them again is safe. The container cannot see the sql folder, so each file's text is piped into `psql` running inside it
(`docker compose exec -T postgres psql`). The alarm journal tables that sql/003 reads are created by Ignition once the journal
profile exists, so on a rebuilt database run `python -m generator.connections <site>` for each site gateway first.
Exit code 0 means every file ran, 1 means one failed (the files after it are not run).
"""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys

from generator.gateway import GatewayError, ROOT, env_value

SQL_DIR = ROOT / "sql"
DOCKER_DESKTOP = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe"
JOURNAL_HINT = ("the alarm journal tables do not exist yet: they are created when the journal profile exists, so run "
                "`python -m generator.connections <site>` for each site gateway first, then apply again")


class SqlError(RuntimeError):
    pass


def files():
    """The SQL files, in the order they must run (their names start with a number)."""
    return sorted(SQL_DIR.glob("*.sql"))


def docker_command():
    """The docker executable: on the PATH, or where Docker Desktop installs it (an assistant's shell can predate Docker)."""
    found = shutil.which("docker.exe") or shutil.which("docker")
    if found:
        return found
    if DOCKER_DESKTOP.exists():
        return str(DOCKER_DESKTOP)
    raise SqlError("docker was not found on the PATH or in Docker Desktop's folder")


def command(docker, user, database):
    return [docker, "compose", "exec", "-T", "postgres", "psql", "-U", user, "-d", database, "-v", "ON_ERROR_STOP=1", "-f", "-"]


def run_file(path, cmd):
    """Pipe one file into psql. Returns (exit code, the output, which includes psql's error messages)."""
    result = subprocess.run(cmd, input=path.read_bytes(), cwd=ROOT, capture_output=True)
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", "replace")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="run the files; without it this only lists them")
    args = parser.parse_args(argv)
    try:
        sql_files = files()
        if not sql_files:
            raise SqlError("no .sql files in %s" % SQL_DIR)
        cmd = command(docker_command(), env_value("POSTGRES_USER"), env_value("POSTGRES_DB"))
    except (SqlError, GatewayError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    print("%d files, each piped into: %s" % (len(sql_files), " ".join(cmd[1:])))
    for path in sql_files:
        print("  %s" % path.name)
    if not args.apply:
        print("(dry run: nothing was run; add --apply)")
        return 0
    for path in sql_files:
        code, output = run_file(path, cmd)
        if code != 0:
            print("FAILED: %s" % path.name, file=sys.stderr)
            print(output.strip()[-1500:], file=sys.stderr)
            if "alarm_events_" in output and "does not exist" in output:
                print("hint: %s" % JOURNAL_HINT, file=sys.stderr)
            return 1
        print("applied %s" % path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
