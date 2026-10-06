"""Fleet-level consistency: the points lists, docker-compose.yml, .env.example, and the simulator's rules must agree.

A wrong inverter count, a clashing port, or a missing license variable should fail here, before anything is started. The
compose file is read as text, not parsed as YAML (the tooling is standard library only), so these checks rely on the file's own
layout: two-space service names under `services:`, one setting per line. They apply to the site gateways' files,
`points/site*.csv`; the OEM-integrated sites, which the hub reads directly, will need their own rules.
"""
import pathlib
import re
import unittest

from generator.gateway import GATEWAYS
from generator.points import read_points
from sim import sunspec
from sim.model import SiteConfig

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")
POINTS_FILES = sorted((ROOT / "points").glob("site*.csv"))
DEFAULTS = SiteConfig()
GATEWAY_INTERNAL_PORT = "8088"
SIM_MODBUS_PORT, SIM_OPCUA_PORT = 15020, 14840  # what the sim image listens on inside its own container


def compose_services(text):
    """{service name: its text} for the services in docker-compose.yml."""
    blocks, name = {}, None
    for line in text.split("\nservices:\n", 1)[1].splitlines():
        if line and not line[0].isspace() and not line.startswith("#"):
            break  # the next top-level key (volumes:)
        match = re.match(r"^  ([a-z0-9_-]+):\s*$", line)
        if match:
            name = match.group(1)
            blocks[name] = []
        elif name:
            blocks[name].append(line)
    return {key: "\n".join(lines) for key, lines in blocks.items()}


def declared_volumes(text):
    top = text.split("\nvolumes:\n", 1)[1]
    return set(re.findall(r"^  ([a-z0-9_-]+):\s*$", top, re.MULTILINE))


def setting(block, name, default=None):
    """The value of `NAME: value` in a service block, quotes removed, or the default."""
    match = re.search(r"^\s+%s:[ \t]*\"?([^\"#\n]+?)\"?[ \t]*(?:#.*)?$" % re.escape(name), block, re.MULTILINE)
    return match.group(1) if match else default


def published_ports(block):
    """[(host port, container port)] of the loopback ports a service publishes."""
    return [(int(h), int(c)) for h, c in re.findall(r"\"127\.0\.0\.1:(\d+):(\d+)\"", block)]


SERVICES = compose_services(COMPOSE)


def sites():
    """(file name, site, its rows) for every site in every points/site*.csv."""
    for path in POINTS_FILES:
        by_site = {}
        for row in read_points(path):
            by_site.setdefault(row.site, []).append(row)
        for site, rows in by_site.items():
            yield path.name, site, rows


class SiteListTests(unittest.TestCase):
    def test_there_is_a_points_list_for_site_1_and_site_2(self):
        self.assertEqual(sorted({site for _, site, _ in sites()}), ["site1", "site2"])

    def test_unit_ids_follow_the_inverter_count(self):
        """ADR 0014 decision 9: inverters 1 to N, then the weather station, then the meter (the simulator's own rule)."""
        for name, site, rows in sites():
            with self.subTest(site=site):
                inverters = [r for r in rows if r.kind == "inverter"]
                units, weather, meter = sunspec.unit_ids(SiteConfig(inverters=len(inverters)))
                self.assertEqual(sorted(r.unit_id for r in inverters), list(units), name)
                self.assertEqual([r.unit_id for r in rows if r.kind == "weather"], [weather], name)
                self.assertEqual([r.unit_id for r in rows if r.kind == "meter"], [meter], name)

    def test_one_rating_one_host_and_the_simulators_fixed_ports(self):
        for name, site, rows in sites():
            with self.subTest(site=site):
                self.assertEqual(len({r.rated_kw for r in rows if r.kind == "inverter"}), 1, "the simulator has one inverter rating")
                self.assertEqual(len({r.host for r in rows}), 1, "every device of a site is on its one simulator")
                self.assertEqual({r.port for r in rows if r.protocol == "modbus"}, {SIM_MODBUS_PORT})
                self.assertEqual({r.port for r in rows if r.protocol == "opcua"}, {SIM_OPCUA_PORT})
                self.assertEqual([r.kind for r in rows if r.protocol == "opcua"], ["plantcontroller"], "one plant controller per site")


class SimulatorServiceTests(unittest.TestCase):
    def test_each_sites_host_is_a_simulator_service_shaped_like_its_points_list(self):
        for name, site, rows in sites():
            with self.subTest(site=site):
                host = rows[0].host
                self.assertIn(host, SERVICES, "%s names host %s, which is not a compose service" % (name, host))
                block = SERVICES[host]
                self.assertIn("dockerfile: sim/Dockerfile", block, "%s is not a simulator service" % host)
                inverters = [r for r in rows if r.kind == "inverter"]
                self.assertEqual(int(setting(block, "SIM_INVERTERS", DEFAULTS.inverters)), len(inverters))
                self.assertEqual(float(setting(block, "SIM_INVERTER_KW", DEFAULTS.inverter_ac_w / 1000.0)), inverters[0].rated_kw)

    def test_two_sites_do_not_share_a_simulator(self):
        hosts = [rows[0].host for _, _, rows in sites()]
        self.assertEqual(len(hosts), len(set(hosts)))

    def test_two_simulators_with_the_same_shape_use_different_seeds_so_their_clouds_differ(self):
        seeds = {}
        for _, site, rows in sites():
            seeds.setdefault(setting(SERVICES[rows[0].host], "SIM_SEED", str(DEFAULTS.seed)), []).append(site)
        self.assertTrue(all(len(v) == 1 for v in seeds.values()), seeds)


class GatewayServiceTests(unittest.TestCase):
    def test_each_site_has_a_gateway_service_with_its_volume_port_license_names_and_whitelist_entry(self):
        hub = SERVICES["hub"]
        whitelist = setting(hub, "GATEWAY_NETWORK_WHITELIST", "").split(",")
        for _, site, _ in sites():
            with self.subTest(site=site):
                upper = site.upper()
                self.assertIn(site, SERVICES, "no compose service named %s" % site)
                block = SERVICES[site]
                self.assertIn('"-n", "%s"' % site, block)
                self.assertIn("%s-data:/usr/local/bin/ignition/data" % site, block)
                self.assertIn("%s-data" % site, declared_volumes(COMPOSE))
                self.assertIn("${%s_LICENSE_KEY:-}" % upper, block)
                self.assertIn("${%s_ACTIVATION_TOKEN:-}" % upper, block)
                self.assertIn(site, whitelist, "the hub's whitelist does not list %s" % site)
                self.assertIn(site, GATEWAYS, "generator.gateway does not know %s" % site)
                self.assertIn((GATEWAYS[site][0], int(GATEWAY_INTERNAL_PORT)), published_ports(block))
                self.assertEqual(GATEWAYS[site][1], "%s_API_TOKEN" % upper)
                for name in ("%s_LICENSE_KEY" % upper, "%s_ACTIVATION_TOKEN" % upper, "%s_API_TOKEN" % upper):
                    self.assertRegex(ENV_EXAMPLE, r"(?m)^%s=" % name, "%s is missing from .env.example" % name)

    def test_each_site_gateway_dials_the_hub_over_the_compose_network(self):
        for _, site, _ in sites():
            with self.subTest(site=site):
                block = SERVICES[site]
                self.assertEqual(setting(block, "GATEWAY_NETWORK_0_HOST"), "hub")
                self.assertEqual(setting(block, "GATEWAY_NETWORK_0_PORT"), GATEWAY_INTERNAL_PORT)
                self.assertEqual(setting(block, "GATEWAY_NETWORK_0_DESCRIPTION"), "%s to hub" % site)


class PortTests(unittest.TestCase):
    def test_no_two_services_publish_the_same_port_on_this_pc(self):
        seen = {}
        for service, block in SERVICES.items():
            for host_port, _ in published_ports(block):
                self.assertNotIn(host_port, seen, "port %d is published by both %s and %s" % (host_port, seen.get(host_port), service))
                seen[host_port] = service

    def test_the_native_dosing_control_gateway_keeps_its_ports(self):
        published = {host_port for block in SERVICES.values() for host_port, _ in published_ports(block)}
        self.assertFalse({8088, 5020} & published)  # DosingControl on this PC uses 8088 and its Modbus device 5020


if __name__ == "__main__":
    unittest.main()
