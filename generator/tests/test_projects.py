"""Structure checks for every project in projects/: parents, embedded views, pages, and the rollout plan (ADR 0014 decision 7).

core holds the views both kinds of gateway share; site (every site gateway) and fleet (the hub) inherit it. A child project
runs only when its parent is on the same gateway (Phase 2 finding 56), so these checks keep the repo's three projects consistent
before anything is deployed."""
import json
import pathlib
import unittest

from generator import deploy_all
from generator.gateway import GATEWAYS

PROJECTS = pathlib.Path(__file__).resolve().parents[2] / "projects"
PER = "com.inductiveautomation.perspective"


def load_project(name):
    folder = PROJECTS / name
    return json.loads((folder / "project.json").read_text(encoding="utf-8"))


def view_names(name):
    views = PROJECTS / name / PER / "views"
    return {p.name for p in views.iterdir() if (p / "view.json").is_file()} if views.is_dir() else set()


def available_views(name):
    """The views a project can embed: its own and every ancestor's."""
    found, current = set(), name
    while current:
        found |= view_names(current)
        current = load_project(current).get("parent", "")
    return found


def embedded_paths(node):
    """Every view path a view embeds (a display.view's or a flex repeater's `path` property)."""
    if isinstance(node, dict):
        if node.get("type") in ("ia.display.view", "ia.display.flex-repeater"):
            path = node.get("props", {}).get("path")
            if path:
                yield path
        for value in node.values():
            yield from embedded_paths(value)
    elif isinstance(node, list):
        for item in node:
            yield from embedded_paths(item)


class ProjectTreeTests(unittest.TestCase):
    NAMES = sorted(p.name for p in PROJECTS.iterdir() if (p / "project.json").is_file())

    def test_the_repo_has_core_site_and_fleet(self):
        self.assertEqual(self.NAMES, ["core", "fleet", "site"])

    def test_core_is_inheritable_and_has_no_parent_and_the_others_inherit_it(self):
        self.assertEqual((load_project("core")["inheritable"], load_project("core")["parent"]), (True, ""))
        for name in ("site", "fleet"):
            self.assertEqual((load_project(name)["parent"], load_project(name)["inheritable"]), ("core", False), name)

    def test_every_parent_exists_and_is_inheritable(self):
        for name in self.NAMES:
            parent = load_project(name)["parent"]
            if parent:
                self.assertIn(parent, self.NAMES, name)
                self.assertTrue(load_project(parent)["inheritable"], name)

    def test_every_embedded_view_resolves_in_the_project_or_its_parent(self):
        for name in self.NAMES:
            available = available_views(name)
            for view in (PROJECTS / name / PER / "views").glob("*/view.json"):
                for path in embedded_paths(json.loads(view.read_text(encoding="utf-8"))):
                    self.assertIn(path, available, "%s/%s embeds %s, which neither %s nor its parent holds" % (name, view.parent.name, path, name))

    def test_a_child_does_not_redefine_a_parents_view_by_accident(self):
        for name in self.NAMES:
            parent = load_project(name)["parent"]
            if parent:
                self.assertEqual(view_names(name) & view_names(parent), set(), name)

    def test_every_page_points_at_a_view_the_project_can_show_and_every_view_has_a_resource_file(self):
        for name in self.NAMES:
            config = PROJECTS / name / PER / "page-config" / "config.json"
            if config.is_file():
                for route, page in json.loads(config.read_text(encoding="utf-8"))["pages"].items():
                    self.assertIn(page["viewPath"], available_views(name), "%s %s" % (name, route))
            for view in (PROJECTS / name / PER / "views").glob("*"):
                self.assertTrue((view / "resource.json").is_file(), view)


class RolloutPlanTests(unittest.TestCase):
    def test_the_hub_gets_core_and_fleet_and_every_site_gateway_gets_core_and_site_parent_first(self):
        self.assertEqual(deploy_all.projects_for("hub"), ["core", "fleet"])
        for site in sorted(GATEWAYS):
            if site != "hub":
                self.assertEqual(deploy_all.projects_for(site), ["core", "site"], site)

    def test_every_planned_project_exists_in_the_repo_and_its_parent_comes_before_it(self):
        for gateway in GATEWAYS:
            planned = deploy_all.projects_for(gateway)
            for index, name in enumerate(planned):
                self.assertTrue((PROJECTS / name / "project.json").is_file(), name)
                parent = load_project(name)["parent"]
                if parent:
                    self.assertIn(parent, planned[:index], "%s on %s comes before its parent %s" % (name, gateway, parent))


if __name__ == "__main__":
    unittest.main()
