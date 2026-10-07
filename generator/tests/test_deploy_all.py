"""Tests for generator.deploy_all and the parent-change safeguard in generator.deploy_project."""
import io
import json
import pathlib
import unittest
import zipfile

from generator import deploy_all, deploy_project
from generator.gateway import GatewayError

PROJECTS = pathlib.Path(__file__).resolve().parents[2] / "projects"


class FakeGateway:
    def __init__(self, site, projects=None):
        self.site = site
        self.projects = dict(projects or {})  # name -> {"parent": ...}
        self.log = []

    def project(self, name):
        return self.projects.get(name)

    def import_project(self, name, zip_bytes, overwrite=False):
        self.log.append(("import", name, overwrite))
        parent = json.loads(zipfile.ZipFile(io.BytesIO(zip_bytes)).read("project.json")).get("parent", "")
        self.projects[name] = {"name": name, "parent": parent}

    def rename_project(self, name, new_name):
        self.log.append(("rename", name, new_name))
        self.projects[new_name] = self.projects.pop(name)

    def scan_projects(self):
        self.log.append(("scan",))


class ParentChangeTests(unittest.TestCase):
    SITE = PROJECTS / "site"

    def test_overwriting_a_project_whose_parent_would_change_is_refused_and_left_alone(self):
        gateway = FakeGateway("site1", {"site": {"name": "site", "parent": ""}})
        with self.assertRaisesRegex(GatewayError, "parent.*--recreate"):
            deploy_project.deploy(gateway, self.SITE, overwrite=True)
        self.assertEqual(gateway.log, [])

    def test_recreate_renames_the_old_project_aside_then_imports_a_fresh_one(self):
        gateway = FakeGateway("site1", {"site": {"name": "site", "parent": ""}})
        lines = deploy_project.deploy(gateway, self.SITE, recreate=True)
        self.assertEqual([entry[0] for entry in gateway.log], ["rename", "import", "scan"])
        self.assertEqual(gateway.log[0], ("rename", "site", "site_old"))
        self.assertEqual(gateway.log[1], ("import", "site", False))  # a new project, not an overwrite
        self.assertTrue(lines[0].startswith("recreated project site"))
        self.assertIn("site_old", lines[0])

    def test_recreate_refuses_when_the_aside_name_is_taken(self):
        gateway = FakeGateway("site1", {"site": {"name": "site", "parent": ""}, "site_old": {"name": "site_old"}})
        with self.assertRaisesRegex(GatewayError, "site_old.*already exists"):
            deploy_project.deploy(gateway, self.SITE, recreate=True)
        self.assertEqual(gateway.log, [])

    def test_a_dry_run_says_what_recreate_would_do(self):
        gateway = FakeGateway("site1", {"site": {"name": "site", "parent": ""}})
        lines = deploy_project.deploy(gateway, self.SITE, recreate=True, dry_run=True)
        self.assertTrue(lines[0].startswith("would recreate project site"))
        self.assertEqual(gateway.log, [])

    def test_recreate_on_a_gateway_without_the_project_is_a_plain_create(self):
        gateway = FakeGateway("site1")
        lines = deploy_project.deploy(gateway, self.SITE, recreate=True)
        self.assertEqual([entry[0] for entry in gateway.log], ["import", "scan"])
        self.assertTrue(lines[0].startswith("created project site"))

    def test_an_overwrite_with_the_same_parent_is_still_a_plain_replace(self):
        gateway = FakeGateway("site1", {"site": {"name": "site", "parent": "core"}})
        lines = deploy_project.deploy(gateway, self.SITE, overwrite=True)
        self.assertTrue(lines[0].startswith("replaced project site"))
        self.assertEqual(gateway.log[0], ("import", "site", True))


class DeployAllTests(unittest.TestCase):
    def gateways(self):
        return {name: FakeGateway(name) for name in ("hub", "site1", "site2")}

    def test_each_gateway_gets_its_projects_parent_first(self):
        gateways = self.gateways()
        deploy_all.deploy_all(gateways, PROJECTS)
        imports = {name: [e[1] for e in g.log if e[0] == "import"] for name, g in gateways.items()}
        self.assertEqual(imports, {"hub": ["core", "fleet"], "site1": ["core", "site"], "site2": ["core", "site"]})

    def test_a_second_run_without_overwrite_stops_on_the_first_existing_project(self):
        gateways = self.gateways()
        deploy_all.deploy_all(gateways, PROJECTS)
        with self.assertRaisesRegex(GatewayError, "already exists"):
            deploy_all.deploy_all(gateways, PROJECTS)

    def test_overwrite_replaces_every_project(self):
        gateways = self.gateways()
        deploy_all.deploy_all(gateways, PROJECTS)
        lines = deploy_all.deploy_all(gateways, PROJECTS, overwrite=True)
        self.assertEqual(len([line for line in lines if "replaced project" in line]), 6)

    def test_a_dry_run_changes_nothing_on_any_gateway(self):
        gateways = self.gateways()
        lines = deploy_all.deploy_all(gateways, PROJECTS, dry_run=True)
        self.assertEqual(len(lines), 6 + 3)  # six projects plus a heading for each gateway
        self.assertTrue(all(g.log == [] for g in gateways.values()))


if __name__ == "__main__":
    unittest.main()
