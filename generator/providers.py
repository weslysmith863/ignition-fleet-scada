"""Create the hub's tag provider for a site, so the fleet views can read the site's tags as [<site>]...

    python -m generator.providers site2            # dry run: report only
    python -m generator.providers site2 --apply    # create it if it is missing
    python -m generator.providers oem1 --apply     # an OEM-integrated site: a local provider on the hub

The provider is named by the site ID (ADR 0014 decision 4). For a site gateway (site1, site2) it is a REMOTE provider that points at
the site's `default` provider over the Gateway Network, and the hub holds no copy of the site's tags. For an OEM-integrated site
(oem1 to oem6, ADR 0015) there is no gateway to point at: the hub reads the plant itself, so the provider is a local STANDARD
provider on the hub that holds the tags the generator creates. Like the other tools it never overwrites: an existing provider is
only compared, and a difference is reported (exit code 2). The settings are those of the provider Wes built by hand for site1
(finding 36) and of the hub's own default provider (finding 42).
"""
import argparse
import copy
import sys

from generator import sites
from generator.gateway import GATEWAYS, TAG_PROVIDER_TYPE, GatewayError, RestGateway

REMOTE_PROVIDER_NAME = "default"  # a site gateway's own tags are in its default provider
REMOTE_SETTINGS = {"historyMode": "GatewayNetwork", "historyDriverName": "", "historyProviderName": "",
                   "alarmStatusEnabled": True, "alarmMode": "Queried"}
STANDARD_CONFIG = {
    "profile": {"type": "STANDARD", "allowBackfill": False, "enableTagReferenceStore": True},
    "settings": {"defaultDatasourceName": None, "readPermissions": {"type": "AllOf", "securityLevels": []}, "readOnly": False,
                 "writePermissions": {"type": "AllOf", "securityLevels": []},
                 "editPermissions": {"type": "AllOf", "securityLevels": []}, "valuePersistence": "Database"},
}


def check_site(site):
    if site == "hub":
        raise ValueError("the hub cannot be a remote provider of itself")
    if site not in GATEWAYS and not sites.is_oem(site):
        known = sorted(g for g in GATEWAYS if g != "hub") + list(sites.OEM_SITES)
        raise ValueError("no site named %r (known: %s)" % (site, ", ".join(known)))


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


def standard_provider_body(site):
    """Body for a local STANDARD provider on the hub, for an OEM-integrated site."""
    return {
        "name": site,
        "collection": "core",
        "enabled": True,
        "description": "Local tag provider for the OEM-integrated site %s; created by generator.providers" % site,
        "config": copy.deepcopy(STANDARD_CONFIG),
    }


def provider_body(site):
    return standard_provider_body(site) if sites.is_oem(site) else remote_provider_body(site)


def provider_drift(existing, site):
    config = existing.get("config", {})
    found = {"type": config.get("profile", {}).get("type"), "enabled": existing.get("enabled")}
    wanted = {"type": "STANDARD" if sites.is_oem(site) else "REMOTE", "enabled": True}
    if not sites.is_oem(site):
        found.update(serverName=config.get("settings", {}).get("serverName"), remoteProviderName=config.get("settings", {}).get("remoteProviderName"))
        wanted.update(serverName=site, remoteProviderName=REMOTE_PROVIDER_NAME)
    label = "local" if sites.is_oem(site) else "remote"
    return ["%s tag provider %s: %s is %r, wanted %r" % (label, site, key, found[key], wanted[key]) for key in wanted if found[key] != wanted[key]]


def apply_provider(hub, site, dry_run=False):
    """Returns (lines to print, drift found)."""
    oem = sites.is_oem(site)
    summary = "local tag provider %s" % site if oem else "remote tag provider %s (%s, provider %s)" % (site, site, REMOTE_PROVIDER_NAME)
    existing = hub.tag_provider(site)
    if existing is not None:
        drift = provider_drift(existing, site)
        return (["unchanged: " + summary.split(" (")[0]] if not drift else ["DRIFT: %s" % line for line in drift]), bool(drift)
    if dry_run:
        return ["would create " + summary], False
    hub.create_tag_provider(provider_body(site))
    lines = ["created " + summary]
    if not hub.wait_for_healthy(TAG_PROVIDER_TYPE, site):
        lines.append("WARNING: the %s provider was not healthy after waiting%s" % (
            site, "" if oem else "; check that the %s gateway is on the Gateway Network" % site))
    return lines, False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site", help="the site the hub should reach, for example site2 or oem1")
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
