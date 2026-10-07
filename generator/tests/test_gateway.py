"""Tests for generator.gateway: a tag import that the gateway refuses must not look like success."""
import unittest

from generator.gateway import GatewayError, check_import


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


if __name__ == "__main__":
    unittest.main()
