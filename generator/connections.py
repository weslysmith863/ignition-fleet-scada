"""Create what a site gateway needs to log history: the database connection `fleetdb` (PostgreSQL on the Compose network)
and the SQL Historian provider `Historian` that uses it (ADR 0007, ADR 0011).

    python -m generator.connections site1 --dry-run   # show what would happen
    python -m generator.connections site1             # create what is missing

Like generator.apply, it never overwrites: an existing connection or provider is only compared, and a difference is
reported. The connection comes first because the provider needs it. The password comes from the gitignored .env, goes
through the gateway's encrypt route (finding 8), and only the encrypted value is stored in the connection. The plain
password is never printed and never written to a file.
"""
import argparse
import copy
import sys

from generator.gateway import GatewayError, RestGateway, env_value

NAME = "fleetdb"
HOST, PORT = "postgres", 5432  # the Compose service name: both are containers on one private network
HISTORIAN_NAME = "Historian"
# The settings site 1's provider was created with (ADR 0011). Pruning at one month is the form's default and is still to be
# revisited before the showcase. Nothing here is secret: the database is named by its connection, and the password stays there.
HISTORIAN_SETTINGS = {
    "partition": {"enabled": True, "size": 1, "sizeUnits": "MONTH", "partitionSeedQueryLimit": 2, "optimized": False,
                  "optimizedWindowSeconds": 60},
    "pruning": {"enabled": True, "age": 1, "ageUnits": "MONTH"},
    "trackSce": True,
    "staleMultiplier": 2,
}


def connection_body(username, database, encrypted_password):
    """Body for POST /resources/ignition/database-connection."""
    return {
        "name": NAME,
        "collection": "core",
        "enabled": True,
        "description": "PostgreSQL on the Compose network; created by generator.connections",
        "config": {
            "driver": "PostgreSQL",
            "translator": "POSTGRES",
            "connectURL": "jdbc:postgresql://%s:%d/%s" % (HOST, PORT, database),
            "username": username,
            "password": encrypted_password,
        },
    }


def connection_drift(existing, username, database):
    """Differences between the wanted connection and an existing one. The password is not compared: it is encrypted."""
    config = existing.get("config", {})
    found = {"driver": config.get("driver"), "translator": config.get("translator"),
             "connectURL": config.get("connectURL"), "username": config.get("username"), "enabled": existing.get("enabled")}
    wanted = {"driver": "PostgreSQL", "translator": "POSTGRES", "connectURL": "jdbc:postgresql://%s:%d/%s" % (HOST, PORT, database),
              "username": username, "enabled": True}
    return ["connection %s: %s is %r, wanted %r" % (NAME, key, found[key], wanted[key]) for key in wanted if found[key] != wanted[key]]


def apply_connection(gateway, username, database, plain_password, dry_run=False):
    """Returns (lines to print, drift found)."""
    existing = gateway.database_connection(NAME)
    if existing is not None:
        drift = connection_drift(existing, username, database)
        return (["unchanged: connection %s" % NAME] if not drift else ["DRIFT: %s" % line for line in drift]), bool(drift)
    if dry_run:
        return ["would create connection %s (jdbc:postgresql://%s:%d/%s, user %s, password encrypted by the gateway)"
                % (NAME, HOST, PORT, database, username)], False
    gateway.create_database_connection(connection_body(username, database, gateway.encrypt(plain_password)))
    return ["created connection %s" % NAME], False


def historian_body(database):
    """Body for POST /resources/com.inductiveautomation.historian/historian-provider: a SQL Historian on the named
    database connection."""
    return {
        "name": HISTORIAN_NAME,
        "collection": "core",
        "enabled": True,
        "description": "SQL Historian on %s; created by generator.connections" % database,
        "config": {"profile": {"type": "SqlHistorian"}, "settings": dict(copy.deepcopy(HISTORIAN_SETTINGS), database=database)},
    }


def historian_drift(existing, database):
    """Differences between the wanted provider and an existing one: its kind, its database connection, and whether it is on."""
    config = existing.get("config", {})
    found = {"type": config.get("profile", {}).get("type"), "database": config.get("settings", {}).get("database"),
             "enabled": existing.get("enabled")}
    wanted = {"type": "SqlHistorian", "database": database, "enabled": True}
    return ["Historian provider %s: %s is %r, wanted %r" % (HISTORIAN_NAME, key, found[key], wanted[key]) for key in wanted
            if found[key] != wanted[key]]


def apply_historian(gateway, database, dry_run=False):
    """Returns (lines to print, drift found). `database` is the gateway's name for the connection, not PostgreSQL's."""
    existing = gateway.historian_provider(HISTORIAN_NAME)
    if existing is not None:
        drift = historian_drift(existing, database)
        return (["unchanged: Historian provider %s" % HISTORIAN_NAME] if not drift else ["DRIFT: %s" % line for line in drift]), bool(drift)
    if dry_run:
        return ["would create Historian provider %s (SQL Historian on %s)" % (HISTORIAN_NAME, database)], False
    gateway.create_historian_provider(historian_body(database))
    return ["created Historian provider %s" % HISTORIAN_NAME], False


def apply_all(gateway, username, database, plain_password, dry_run=False):
    """The database connection first, then the provider that uses it. Returns (lines to print, drift found)."""
    lines, drift = apply_connection(gateway, username, database, plain_password, dry_run=dry_run)
    more, more_drift = apply_historian(gateway, NAME, dry_run=dry_run)
    return lines + more, drift or more_drift


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site", help="the gateway to configure, for example site1")
    parser.add_argument("--dry-run", action="store_true", help="report only; change nothing")
    args = parser.parse_args(argv)
    try:
        gateway = RestGateway(args.site)
        lines, drift = apply_all(gateway, env_value("POSTGRES_USER"), env_value("POSTGRES_DB"),
                                 env_value("POSTGRES_PASSWORD"), dry_run=args.dry_run)
        print("== %s ==" % args.site)
        for line in lines:
            print("  %s" % line)
        return 2 if drift else 0
    except GatewayError as error:
        print("error: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
