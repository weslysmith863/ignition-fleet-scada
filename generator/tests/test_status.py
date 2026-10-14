"""Tests for generator.status."""
import unittest

from generator import status
from generator.gateway import GatewayError


class CheckProjectsTests(unittest.TestCase):
    """The check Wes writes: a gateway's /projects/list answer against the projects the repo deploys there."""

    def test_every_expected_project_present_and_enabled_is_fine(self):
        self.assertEqual(status.check_projects([["core", True], ["fleet", True]], ["core", "fleet"]), [])

    def test_a_missing_project_is_one_problem_that_names_it(self):
        problems = status.check_projects([["core", True]], ["core", "fleet"])
        self.assertEqual(len(problems), 1)
        self.assertIn("fleet", problems[0])

    def test_a_disabled_project_is_one_problem_that_names_it(self):
        problems = status.check_projects([["core", True], ["fleet", False]], ["core", "fleet"])
        self.assertEqual(len(problems), 1)
        self.assertIn("fleet", problems[0])

    def test_two_missing_projects_are_two_problems(self):
        self.assertEqual(len(status.check_projects([], ["core", "fleet"])), 2)

    def test_a_project_nobody_expects_is_not_a_problem(self):
        listed = [["core", True], ["fleet", True], ["test1", True], ["scratch", False]]
        self.assertEqual(status.check_projects(listed, ["core", "fleet"]), [])

    def test_pairs_may_come_as_tuples(self):
        self.assertEqual(status.check_projects([("core", True), ("site", True)], ["core", "site"]), [])


class SmallChecksTests(unittest.TestCase):
    def test_the_right_name_is_fine_and_a_crossed_port_is_not(self):
        self.assertEqual(status.check_name("site1", "site1"), [])
        problems = status.check_name("site2", "site1")
        self.assertEqual(len(problems), 1)
        self.assertIn("site2", problems[0])
        self.assertIn("site1", problems[0])

    def test_every_listed_problem_is_reported_with_its_title(self):
        problems = status.check_problems([{"title": "Database connection fleetdb is faulted"}, "something odd"])
        self.assertEqual(len(problems), 2)
        self.assertIn("fleetdb", problems[0])
        self.assertIn("something odd", problems[1])

    def test_no_listed_problems_is_fine(self):
        self.assertEqual(status.check_problems([]), [])


class FakeGateway:
    def __init__(self, name, reported=None, problems=(), projects=None, refuse_key=False):
        self.reported = name if reported is None else reported
        self._problems = list(problems)
        self.projects = projects if projects is not None else [["core", True], ["fleet" if name == "hub" else "site", True], ["test1", True]]
        self.refuse_key = refuse_key
        self.calls = []

    def _ask(self, what):
        self.calls.append(what)
        if self.refuse_key:
            raise GatewayError("GET /overview/name -> HTTP 401: unauthorized")

    def reported_name(self):
        self._ask("name")
        return self.reported

    def problems(self):
        self._ask("problems")
        return self._problems

    def project_list(self):
        self._ask("projects")
        return self.projects


def cmms_ok(url):
    return {"status": "ok", "tickets": 4}


class StatusTests(unittest.TestCase):
    def gateways(self, **overrides):
        gateways = {name: FakeGateway(name) for name in ("hub", "site1", "site2")}
        gateways.update(overrides)
        return gateways

    def test_a_healthy_fleet_passes_every_check(self):
        lines, failed, total = status.status(self.gateways(), cmms_ok)
        self.assertEqual((failed, total), (0, 3 * 4 + 1))  # four checks per gateway and the CMMS
        self.assertFalse([line for line in lines if "FAIL" in line])

    def test_a_refused_key_is_one_failure_and_the_gateway_is_asked_nothing_else(self):
        gateway = FakeGateway("site1", refuse_key=True)
        lines, failed, total = status.status(self.gateways(site1=gateway), cmms_ok)
        self.assertEqual(failed, 1)
        self.assertEqual(gateway.calls, ["name"])
        self.assertTrue([line for line in lines if "401" in line])

    def test_a_crossed_port_fails_the_name_check_only(self):
        lines, failed, total = status.status(self.gateways(site1=FakeGateway("site1", reported="site2")), cmms_ok)
        self.assertEqual(failed, 1)
        self.assertTrue([line for line in lines if "crossed" in line])

    def test_a_problem_the_gateway_lists_fails_its_check(self):
        gateway = FakeGateway("hub", problems=[{"title": "Database connection fleetdb is faulted"}])
        lines, failed, total = status.status(self.gateways(hub=gateway), cmms_ok)
        self.assertEqual(failed, 1)
        self.assertTrue([line for line in lines if "fleetdb" in line])

    def test_a_missing_project_fails_the_project_check_and_names_it(self):
        gateway = FakeGateway("site2", projects=[["core", True]])
        lines, failed, total = status.status(self.gateways(site2=gateway), cmms_ok)
        self.assertEqual(failed, 1)
        self.assertTrue([line for line in lines if "site" in line and "-" in line])

    def test_the_projects_each_gateway_must_have_come_from_deploy_all(self):
        lines, failed, total = status.status(self.gateways(), cmms_ok)
        self.assertTrue([line for line in lines if "(core, fleet)" in line])
        self.assertEqual(len([line for line in lines if "(core, site)" in line]), 2)

    def test_the_cmms_being_down_is_one_failure(self):
        def down(url):
            raise OSError("connection refused")
        lines, failed, total = status.status(self.gateways(), down)
        self.assertEqual(failed, 1)
        self.assertTrue([line for line in lines if "connection refused" in line])

    def test_the_cmms_answering_something_else_is_one_failure(self):
        lines, failed, total = status.status(self.gateways(), lambda url: {"status": "starting"})
        self.assertEqual(failed, 1)


if __name__ == "__main__":
    unittest.main()
