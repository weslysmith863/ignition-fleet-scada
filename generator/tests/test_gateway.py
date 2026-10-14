"""Tests for generator.gateway: a tag import that the gateway refuses must not look like success, and the status calls
turn the gateway's real answers into the simple shapes the checks use."""
import unittest

from generator.gateway import GatewayError, RestGateway, check_import


class CheckImportTests(unittest.TestCase):
    def test_a_clean_import_passes(self):
        check_import({"successCount": 4, "failureCount": 0, "failures": []})

    def test_a_response_without_counts_passes_as_it_did_before(self):
        check_import({})
        check_import(None)

    def test_a_failure_raises_with_the_gateways_own_message(self):
        failed = {"successCount": 0, "failureCount": 1,
                  "failures": [{"quality": "Bad", "diagnosticMessage": "Insufficient Tag Provider Edit Permissions"}]}
        with self.assertRaisesRegex(GatewayError, "Insufficient Tag Provider Edit Permissions"):
            check_import(failed)

    def test_the_message_counts_the_failures_and_hints_at_permissions_for_that_one_error(self):
        failed = {"successCount": 2, "failureCount": 3, "failures": [
            {"diagnosticMessage": "Insufficient Tag Provider Edit Permissions"}, {"diagnosticMessage": "Other"}, {}]}
        with self.assertRaises(GatewayError) as caught:
            check_import(failed)
        text = str(caught.exception)
        self.assertIn("3 of 5", text)
        self.assertIn("security level", text)

    def test_other_failures_do_not_get_the_permissions_hint(self):
        with self.assertRaises(GatewayError) as caught:
            check_import({"successCount": 0, "failureCount": 1, "failures": [{"diagnosticMessage": "Bad type"}]})
        self.assertNotIn("security level", str(caught.exception))


class AnsweringGateway(RestGateway):
    """A gateway that answers every call with one canned answer. It skips RestGateway's setup, which reads the API key from
    .env (a clean checkout, such as CI, has none)."""

    def __init__(self, answer):
        self.answer = answer

    def _call(self, method, path, body=None, content_type="application/json", allow_404=False):
        return self.answer


class StatusAnswerTests(unittest.TestCase):
    """The canned answers are shaped like what Ignition 8.3.9 returned on 2026-10-14 (fields trimmed). The first version of
    project_list assumed a plain list of pairs; the real answer is a record per project inside "items", and only a run against
    a real gateway showed it."""

    def test_the_project_list_becomes_name_and_enabled_pairs(self):
        answer = {"items": [
            {"name": "core", "title": "Core", "enabled": True, "parent": "", "inheritable": True},
            {"name": "site", "title": "Site", "enabled": True, "parent": "core", "inheritable": False},
            {"name": "test1", "title": "", "enabled": False, "parent": "", "inheritable": False}],
            "metadata": {"total": 3, "matching": 3, "limit": -1, "offset": 0}}
        self.assertEqual(AnsweringGateway(answer).project_list(), [["core", True], ["site", True], ["test1", False]])

    def test_the_reported_name_is_the_gateway_name_field(self):
        self.assertEqual(AnsweringGateway({"gatewayName": "hub", "cleanGatewayName": "hub"}).reported_name(), "hub")

    def test_the_problems_are_the_items_of_the_answer(self):
        empty = {"items": [], "metadata": {"total": 0, "matching": 0, "limit": -1, "offset": 0}}
        self.assertEqual(AnsweringGateway(empty).problems(), [])
        one = {"items": [{"title": "Database connection fleetdb is faulted"}], "metadata": {"total": 1}}
        self.assertEqual(AnsweringGateway(one).problems(), [{"title": "Database connection fleetdb is faulted"}])


if __name__ == "__main__":
    unittest.main()
