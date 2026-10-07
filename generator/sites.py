"""Where each site's objects live (ADR 0015). Pure functions.

A site gateway (site1, site2) runs its own site: its devices and tags are on that gateway, in its `default` provider. An
OEM-integrated site (oem1 to oem6) has no gateway of its own: the hub reads its plant directly over Modbus, with the devices on
the hub and the tags in a provider named for the site, so the fleet sees every site as [<site>]Meter/POI_MW. Device names are
unique across a whole gateway, so an OEM device is named <site>_<device> (oem1_Inv1) while its tag keeps the plain name (Inv1).
"""

OEM_SITES = ("oem1", "oem2", "oem3", "oem4", "oem5", "oem6")


def is_oem(site):
    return site in OEM_SITES


def gateway_for(site):
    """The gateway whose REST API holds the site's devices and tags."""
    return "hub" if is_oem(site) else site


def provider_for(site):
    """The tag provider, on that gateway, that holds the site's tags."""
    return site if is_oem(site) else "default"


def resource_name(site, device):
    """The Modbus device's name on its gateway."""
    return "%s_%s" % (site, device) if is_oem(site) else device
