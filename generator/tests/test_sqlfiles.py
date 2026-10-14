"""Tests for generator.sqlfiles: the SQL files are applied in order, only with --apply, and stop at the first failure.

Nothing here needs Docker or a .env file: the docker call and the .env values are replaced.
"""
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from generator import sqlfiles


class Result:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def run_main(argv, results=None, docker="docker.exe"):
    """Run main() with docker and .env faked. Returns (exit code, stdout, stderr, the calls to subprocess.run)."""
    calls = []
    queue = list(results or [])

    def fake_run(cmd, input=None, cwd=None, capture_output=None):
        calls.append({"cmd": cmd, "input": input, "cwd": cwd})
        return queue.pop(0) if queue else Result()

    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sqlfiles.subprocess, "run", fake_run), \
            mock.patch.object(sqlfiles, "docker_command", lambda: docker), \
            mock.patch.object(sqlfiles, "env_value", lambda name: {"POSTGRES_USER": "u", "POSTGRES_DB": "d"}[name]), \
            redirect_stdout(out), redirect_stderr(err):
        code = sqlfiles.main(argv)
    return code, out.getvalue(), err.getvalue(), calls


class SqlFilesTests(unittest.TestCase):
    def test_the_repos_files_are_found_in_numbered_order(self):
        names = [path.name for path in sqlfiles.files()]
        self.assertEqual(names, sorted(names))
        self.assertTrue(names[0].startswith("001_"))
        self.assertGreaterEqual(len(names), 5)

    def test_the_command_runs_psql_inside_the_postgres_container_and_reads_the_file_from_stdin(self):
        self.assertEqual(sqlfiles.command("docker.exe", "u", "d"),
                         ["docker.exe", "compose", "exec", "-T", "postgres", "psql", "-U", "u", "-d", "d", "-v", "ON_ERROR_STOP=1", "-f", "-"])

    def test_without_apply_it_only_lists_and_runs_nothing(self):
        code, out, _, calls = run_main([])
        self.assertEqual((code, calls), (0, []))
        self.assertIn("dry run", out)
        for path in sqlfiles.files():
            self.assertIn(path.name, out)

    def test_with_apply_every_file_is_run_in_order_with_its_own_text(self):
        code, out, _, calls = run_main(["--apply"])
        files = sqlfiles.files()
        self.assertEqual(code, 0)
        self.assertEqual([call["input"] for call in calls], [path.read_bytes() for path in files])
        self.assertEqual({call["cwd"] for call in calls}, {sqlfiles.ROOT})
        self.assertEqual([line.split()[-1] for line in out.splitlines() if line.startswith("applied")], [p.name for p in files])

    def test_it_stops_at_the_first_failing_file_and_says_which(self):
        code, _, err, calls = run_main(["--apply"], results=[Result(), Result(1, stderr=b"ERROR: boom")])
        self.assertEqual((code, len(calls)), (1, 2))
        self.assertIn("FAILED: %s" % sqlfiles.files()[1].name, err)
        self.assertIn("boom", err)

    def test_a_missing_journal_table_gets_a_hint(self):
        code, _, err, _ = run_main(["--apply"], results=[Result(), Result(), Result(1, stderr=b'ERROR: relation "alarm_events_site1" does not exist')])
        self.assertEqual(code, 1)
        self.assertIn("generator.connections", err)

    def test_a_missing_docker_is_an_error_not_a_crash(self):
        err = io.StringIO()
        with mock.patch.object(sqlfiles, "docker_command", side_effect=sqlfiles.SqlError("docker was not found")), redirect_stderr(err):
            self.assertEqual(sqlfiles.main([]), 1)
        self.assertIn("docker was not found", err.getvalue())


if __name__ == "__main__":
    unittest.main()
