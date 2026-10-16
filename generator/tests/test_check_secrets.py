"""Tests for scripts/check_secrets.py: the line checks and the reasoned, line-level allow marker.

The scanner is a script, not a package, so it is loaded from its path. These tests are in the generator folder only so the
existing test command runs them. The sample lines below are not credentials; each carries its own marker saying so."""
import importlib.util
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "check_secrets.py"
spec = importlib.util.spec_from_file_location("check_secrets", SCRIPT)
check_secrets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_secrets)

PASSWORD_LINE = 'password = "hunter22hunter"'  # check-secrets: allow password-literal - a test sample, not a credential
TOKEN_LINE = "token: " + "A" * 4 + ":" + "b" * 45
JWE_LINE = "x = eyJ" + "a" * 30
# Fixtures that look like what the scanner flags, or like a malformed marker, are assembled here at run time. Written out in
# this file they would trip the very scanner the file tests. Nothing below is a credential.
MARKER = "check-secrets:" + " allow"
CALL_ASSIGNED_TO_A_PASSWORD_NAME = "key_store_pass" + "word = gateway.encrypt(value)"


class UnmarkedLineTests(unittest.TestCase):
    def test_a_literal_password_is_flagged(self):
        self.assertEqual(check_secrets.credential_problems(PASSWORD_LINE), ["password assigned a literal value"])

    def test_a_call_result_assigned_to_a_password_name_is_also_flagged_so_name_it_for_what_it_is(self):
        # The pattern cannot tell a call from a literal; that is why a variable holding ciphertext is not named ..._password.
        self.assertTrue(check_secrets.credential_problems(CALL_ASSIGNED_TO_A_PASSWORD_NAME))

    def test_a_long_token_and_a_jwe_looking_string_are_flagged(self):
        self.assertEqual(check_secrets.credential_problems(TOKEN_LINE), ["long name:secret token"])
        self.assertEqual(check_secrets.credential_problems(JWE_LINE), ["JWE or JWT-looking string"])

    def test_an_ordinary_line_and_a_placeholder_pass(self):
        self.assertEqual(check_secrets.credential_problems("x = compute(1, 2)"), [])
        self.assertEqual(check_secrets.credential_problems("HUB_API_TOKEN=paste-token-here"), [])


class AllowMarkerTests(unittest.TestCase):
    def marked(self, check="password-literal", reason="a documented dev default"):
        return PASSWORD_LINE + "  # " + MARKER + " %s - %s" % (check, reason)

    def test_a_marker_naming_the_check_with_a_reason_allows_that_line(self):
        self.assertEqual(check_secrets.credential_problems(self.marked()), [])

    def test_a_marker_for_a_different_check_does_not_allow_it(self):
        self.assertEqual(check_secrets.credential_problems(self.marked(check="jwe")), ["password assigned a literal value"])

    def test_a_marker_without_a_reason_is_refused_and_the_line_is_still_flagged(self):
        problems = check_secrets.credential_problems(PASSWORD_LINE + "  # " + MARKER + " password-literal")
        self.assertIn("password assigned a literal value", problems)
        self.assertTrue(any("allow marker" in p for p in problems), problems)

    def test_a_marker_without_a_check_name_is_refused(self):
        problems = check_secrets.credential_problems(PASSWORD_LINE + "  # " + MARKER + " - because")
        self.assertIn("password assigned a literal value", problems)

    def test_a_marker_allows_only_the_named_check_on_a_line_that_trips_two(self):
        line = PASSWORD_LINE + " " + JWE_LINE + "  # " + MARKER + " password-literal - sample"
        self.assertEqual(check_secrets.credential_problems(line), ["JWE or JWT-looking string"])

    def test_a_marker_on_one_line_does_not_cover_the_next(self):
        text = [self.marked(), PASSWORD_LINE]
        self.assertEqual([check_secrets.credential_problems(line) for line in text], [[], ["password assigned a literal value"]])


class EnvValueTests(unittest.TestCase):
    SECRETS = {"HUB_API_TOKEN": "not-a-real-value-123"}

    def test_a_value_from_the_local_env_is_reported_wherever_it_appears(self):
        problems = check_secrets.env_value_problems("a.py", "x = 'not-a-real-value-123'", self.SECRETS)
        self.assertEqual(problems, ["a.py: contains the value of HUB_API_TOKEN from your local .env"])

    def test_an_allow_marker_cannot_hide_a_value_from_the_local_env(self):
        marked = "x = 'not-a-real-value-123'  # " + MARKER + " password-literal - a documented default"
        self.assertEqual(len(check_secrets.env_value_problems("a.py", marked, self.SECRETS)), 1)

    def test_a_file_without_the_value_has_no_problem(self):
        self.assertEqual(check_secrets.env_value_problems("a.py", "x = 1", self.SECRETS), [])


class BinaryFileTests(unittest.TestCase):
    """A recorded GIF once tripped the token-shape check by chance (compressed pixels contain long runs of letters and digits).
    Binary files now skip that check only; the forbidden names and the values from the local .env still apply to them."""
    SECRETS = {"HUB_API_TOKEN": "not-a-real-value-123"}

    def test_git_calls_a_file_binary_when_a_nul_byte_is_in_the_first_8000_bytes(self):
        self.assertTrue(check_secrets.is_binary(b"a" * 7999 + b"\0"))
        self.assertFalse(check_secrets.is_binary(b"a" * 8000 + b"\0"))
        self.assertFalse(check_secrets.is_binary(b"plain text\n"))

    def test_a_credential_shaped_line_in_a_text_file_is_flagged_with_its_line_number(self):
        raw = ("x = 1\n" + TOKEN_LINE + "\n").encode()
        self.assertEqual(check_secrets.file_problems("a.txt", raw, {}),
                         ["a.txt:2: looks like a leaked credential (long name:secret token)"])

    def test_the_same_line_inside_a_binary_file_is_not_flagged(self):
        raw = b"GIF89a\0\1" + TOKEN_LINE.encode() + b"\0"
        self.assertEqual(check_secrets.file_problems("a.gif", raw, {}), [])

    def test_a_value_from_the_local_env_is_still_found_inside_a_binary_file(self):
        raw = b"GIF89a\0\1" + b"not-a-real-value-123" + b"\0"
        self.assertEqual(check_secrets.file_problems("a.gif", raw, self.SECRETS),
                         ["a.gif: contains the value of HUB_API_TOKEN from your local .env"])

    def test_a_binary_file_without_any_value_or_shape_has_no_problem(self):
        self.assertEqual(check_secrets.file_problems("a.gif", b"GIF89a\0\1\2\3", self.SECRETS), [])


class ForbiddenFileTests(unittest.TestCase):
    def test_env_files_and_gateway_backups_are_forbidden_anywhere_in_the_tree(self):
        for path in (".env", "sub/dir/.env", ".env.local", "a/.env.production", "backup.gwbk", "x/y/gateway.gwbk"):
            self.assertTrue(check_secrets.forbidden_file(path), path)

    def test_the_example_file_and_ordinary_files_are_allowed_including_images(self):
        for path in (".env.example", "docs/images/fault-to-ticket.gif", "README.md", "environment.py"):
            self.assertFalse(check_secrets.forbidden_file(path), path)


if __name__ == "__main__":
    unittest.main()
