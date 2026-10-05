"""Create the database connection a site gateway logs to: `fleetdb`, PostgreSQL on the Compose network (ADR 0007).

    python -m generator.connections site1 --dry-run   # show what would happen
    python -m generator.connections site1             # create it if it is missing

Like generator.apply, it never overwrites: an existing connection is only compared, and a difference is reported. The
password comes from the gitignored .env, goes through the gateway's encrypt route (finding 8), and only the encrypted
value is stored in the connection. The plain password is never printed and never written to a file.
"""
import argparse
import sys

from generator.gateway import GatewayError, RestGateway, env_value

NAME = "fleetdb"
HOST, PORT = "postgres", 5432  # the Compose service name: both are containers on one private network


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site", help="the gateway to configure, for example site1")
    parser.add_argument("--dry-run", action="store_true", help="report only; change nothing")
    args = parser.parse_args(argv)
    try:
        gateway = RestGateway(args.site)
        lines, drift = apply_connection(gateway, env_value("POSTGRES_USER"), env_value("POSTGRES_DB"),
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
