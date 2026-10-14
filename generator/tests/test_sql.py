"""The repo's SQL files (sql/) must stay re-runnable and agree with the rest of the repo.

The files are applied by hand with psql (nothing applies them after a rebuild yet), so a file that fails the second time it is run,
or a site list that has drifted from the points lists, should fail here first.
"""
import pathlib
import re
import unittest

from generator import connections
from generator.points import read_points

ROOT = pathlib.Path(__file__).resolve().parents[2]
SQL_FILES = sorted((ROOT / "sql").glob("*.sql"))
TEXT = {path.name: path.read_text(encoding="utf-8") for path in SQL_FILES}


def statements(text):
    """The SQL with comment lines removed."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))


class SqlFileTests(unittest.TestCase):
    def test_files_are_numbered_from_001_with_no_gap(self):
        numbers = [int(path.name[:3]) for path in SQL_FILES]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_every_file_can_be_run_twice(self):
        for name, text in TEXT.items():
            body = statements(text)
            with self.subTest(name):
                self.assertFalse(re.findall(r"CREATE\s+TABLE\s+(?!IF NOT EXISTS)", body), "CREATE TABLE without IF NOT EXISTS")
                self.assertFalse(re.findall(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?!IF NOT EXISTS)", body), "CREATE INDEX without IF NOT EXISTS")
                for view in re.findall(r"CREATE\s+VIEW\s+(\w+)", body):  # allowed only when the same view is dropped first
                    self.assertRegex(body, r"DROP\s+VIEW\s+IF\s+EXISTS\s+%s\b" % view, "CREATE VIEW %s without DROP VIEW IF EXISTS" % view)
                inserts = len(re.findall(r"\bINSERT\s+INTO\b", body))
                self.assertEqual(inserts, len(re.findall(r"ON\s+CONFLICT", body)), "an INSERT without ON CONFLICT")

    def test_each_file_says_how_to_apply_it(self):
        for name, text in TEXT.items():
            with self.subTest(name):
                self.assertIn("psql -U fleet -d fleet", text)


class SitesTests(unittest.TestCase):
    seeded = {site: int(count) for site, count in re.findall(r"\('(\w+)',\s*(\d+)\)", statements(TEXT["004_sites.sql"]))}

    def test_the_sites_table_has_the_points_lists_inverter_counts(self):
        expected = {}
        for path in sorted((ROOT / "points").glob("site*.csv")):
            rows = read_points(path)
            expected[rows[0].site] = len([row for row in rows if row.kind == "inverter"])
        self.assertEqual(self.seeded, expected)

    def test_the_downtime_view_reads_the_journal_of_every_seeded_site(self):
        view = statements(TEXT["003_downtime_view.sql"])
        for site in self.seeded:
            events_table, _ = connections.journal_table_names(site)
            with self.subTest(site):
                self.assertRegex(view, r"'%s' AS site, .* FROM %s\b" % (site, events_table))
        branches = re.findall(r"FROM (alarm_events_\w+)", view)
        self.assertEqual(sorted(branches), sorted(connections.journal_table_names(s)[0] for s in self.seeded))


if __name__ == "__main__":
    unittest.main()
