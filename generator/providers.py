"""Create the hub's remote tag provider for a site gateway, so the fleet views can read the site's tags as [<site>]...

    python -m generator.providers site2            # dry run: report only
    python -m generator.providers site2 --apply    # create it if it is missing

The provider is named by the site ID and points at the site's `default` provider over the Gateway Network (ADR 0014 decision
4). The hub holds no copy of the site's tags. Like the other tools it never overwrites: an existing provider is only compared,
and a difference is reported (exit code 2). The settings are the ones of the provider Wes built by hand for site1
(Phase 2 finding 36).
"""
import argparse
import copy
import sys

from generator.gateway import GATEWAYS, TAG_PROVIDER_TYPE, GatewayError, RestGateway

REMOTE_PROVIDER_NAME = "default"  # a site gateway's own tags are in its default provider
REMOTE_SETTINGS = {"historyMode": "GatewayNetwork", "historyDriverName": "", "historyProviderName": "",
                   "alarmStatusEnabled": True, "alarmMode": "Queried"}


def check_site(site):
    if site == "hub":
        raise ValueError("the hub cannot be a remote provider of itself")
    if site not in GATEWAYS:
        raise ValueError("no site gateway named %r (known: %s)" % (site, ", ".join(sorted(g for g in GATEWAYS if g != "hub"))))


def remote_provider_body(site):
    """Body for POST /resources/ignition/tag-provider: a REMOTE provider on the hub for one site gateway."""
    settings = dict(copy.deepcopy(REMOTE_SETTINGS), serverName=site, remoteProviderName=REMOTE_PROVIDER_NAME)
    return {
        "name": site,
        "collection": "core",
        "enabled": True,
        "description": "Remote tag provider for %s; created by generator.providers" % site,
        "config": {"profile": {"type": "REMOTE", "allowBackfill": False, "enableTagReferenceStore": True}, "settings": settings},
    }


def provider_drift(existing, site):
    config = existing.get("config", {})
    found = {"type": config.get("profile", {}).get("type"), "serverName": config.get("settings", {}).get("serverName"),
             "remoteProviderName": config.get("settings", {}).get("remoteProviderName"), "enabled": existing.get("enabled")}
    wanted = {"type": "REMOTE", "serverName": site, "remoteProviderName": REMOTE_PROVIDER_NAME, "enabled": True}
    return ["remote tag provider %s: %s is %r, wanted %r" % (site, key, found[key], wanted[key]) for key in wanted if found[key] != wanted[key]]


def apply_provider(hub, site, dry_run=False):
    """Returns (lines to print, drift found)."""
    summary = "remote tag provider %s (%s, provider %s)" % (site, site, REMOTE_PROVIDER_NAME)
    existing = hub.tag_provider(site)
    if existing is not None:
        drift = provider_drift(existing, site)
        return (["unchanged: remote tag provider %s" % site] if not drift else ["DRIFT: %s" % line for line in drift]), bool(drift)
    if dry_run:
        return ["would create " + summary], False
    hub.create_tag_provider(remote_provider_body(site))
    lines = ["created " + summary]
    if not hub.wait_for_healthy(TAG_PROVIDER_TYPE, site):
        lines.append("WARNING: the %s provider was not healthy after waiting; check that the %s gateway is on the Gateway Network" % (site, site))
    return lines, False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site", help="the site gateway the hub should reach, for example site2")
    parser.add_argument("--apply", action="store_true", help="create the provider; without it nothing is changed")
    args = parser.parse_args(argv)
    try:
        check_site(args.site)
        lines, drift = apply_provider(RestGateway("hub"), args.site, dry_run=not args.apply)
    except (ValueError, GatewayError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    print("== hub ==")
    for line in lines:
        print("  %s" % line)
    if not args.apply and any(line.startswith("would create") for line in lines):
        print("  (nothing changed; add --apply to create it)")
    return 2 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
