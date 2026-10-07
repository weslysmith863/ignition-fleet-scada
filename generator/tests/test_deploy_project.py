"""Tests for generator.deploy_project: the repo folder becomes a project zip, and nothing is replaced without --overwrite."""
import io
import json
import pathlib
import tempfile
import unittest
import zipfile

from generator import deploy_project
from generator.gateway import GatewayError

SITE = pathlib.Path(__file__).resolve().parents[2] / "projects" / "site"


class FakeGateway:
    site = "site1"

    def __init__(self, existing=None):
        self.existing = existing
        self.imports = []
        self.scans = 0

    def project(self, name):
        return self.existing

    def import_project(self, name, zip_bytes, overwrite=False):
        self.imports.append((name, zip_bytes, overwrite))

    def scan_projects(self):
        self.scans += 1


class ProjectZipTests(unittest.TestCase):
    def test_the_real_site_project_zips_with_project_json_at_the_root_and_relative_paths(self):
        names = zipfile.ZipFile(io.BytesIO(deploy_project.project_zip(SITE))).namelist()
        self.assertIn("project.json", names)
        self.assertIn("com.inductiveautomation.perspective/page-config/config.json", names)
        self.assertIn("com.inductiveautomation.perspective/views/Overview/view.json", names)
        self.assertFalse([n for n in names if "\\" in n or n.startswith("/") or n.startswith("site/")])

    def test_every_json_file_in_the_site_project_is_valid_and_every_view_has_a_resource_file(self):
        for path in SITE.rglob("*.json"):
            json.loads(path.read_text(encoding="utf-8"))
        for view in (SITE / "com.inductiveautomation.perspective" / "views").iterdir():
            self.assertTrue((view / "view.json").is_file(), view)
            self.assertTrue((view / "resource.json").is_file(), view)

    def test_every_page_in_the_page_config_points_at_a_view_that_exists(self):
        perspective = SITE / "com.inductiveautomation.perspective"
        pages = json.loads((perspective / "page-config" / "config.json").read_text(encoding="utf-8"))["pages"]
        for route, page in pages.items():
            self.assertTrue((perspective / "views" / page["viewPath"] / "view.json").is_file(), route)

    def test_every_navigation_link_is_a_page_route_and_not_a_full_address(self):
        # Perspective puts the project's own address in front of a link's url, so "/trends" is right and
        # "/data/perspective/client/site/trends" becomes a doubled address that is not a page (found 2026-10-05).
        perspective = SITE / "com.inductiveautomation.perspective"
        routes = set(json.loads((perspective / "page-config" / "config.json").read_text(encoding="utf-8"))["pages"])

        def links(node):
            if isinstance(node, dict):
                if node.get("type") == "ia.navigation.link":
                    yield node["props"]["url"]
                for value in node.values():
                    yield from links(value)
            elif isinstance(node, list):
                for item in node:
                    yield from links(item)

        found = [url for view in (perspective / "views").glob("*/view.json")
                 for url in links(json.loads(view.read_text(encoding="utf-8")))]
        self.assertTrue(found)
        for url in found:
            self.assertIn(url, routes)

    def test_a_folder_without_project_json_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(GatewayError, "no project.json"):
                deploy_project.project_zip(folder)


class DeployTests(unittest.TestCase):
    def test_a_missing_project_is_created_and_the_gateway_is_asked_to_scan(self):
        gateway = FakeGateway()
        lines = deploy_project.deploy(gateway, SITE)
        self.assertTrue(lines[0].startswith("created project site"))
        self.assertEqual([(name, overwrite) for name, _, overwrite in gateway.imports], [("site", False)])
        self.assertEqual(gateway.scans, 1)

    def test_an_existing_project_is_refused_without_overwrite_and_left_alone(self):
        gateway = FakeGateway(existing={"name": "site"})
        with self.assertRaisesRegex(GatewayError, "already exists.*--overwrite"):
            deploy_project.deploy(gateway, SITE)
        self.assertEqual((gateway.imports, gateway.scans), ([], 0))

    def test_overwrite_replaces_an_existing_project(self):
        gateway = FakeGateway(existing={"name": "site", "parent": "core"})
        lines = deploy_project.deploy(gateway, SITE, overwrite=True)
        self.assertTrue(lines[0].startswith("replaced project site"))
        self.assertEqual([(name, overwrite) for name, _, overwrite in gateway.imports], [("site", True)])

    def test_a_dry_run_changes_nothing(self):
        for existing in (None, {"name": "site", "parent": "core"}):
            gateway = FakeGateway(existing=existing)
            lines = deploy_project.deploy(gateway, SITE, overwrite=True, dry_run=True)
            self.assertTrue(lines[0].startswith("would "))
            self.assertEqual((gateway.imports, gateway.scans), ([], 0))


if __name__ == "__main__":
    unittest.main()
