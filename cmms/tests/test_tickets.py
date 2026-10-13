import os
import tempfile
import unittest
from datetime import datetime, timezone

from cmms.tickets import TicketError, TicketStore, normalize_time

START = "2026-10-13T18:34:47.476Z"
START_MS = 1791916487476  # the same instant as START
BODY = {"site": "site1", "equipment": "Inv1", "fault_started_at": START}


class NormalizeTimeTests(unittest.TestCase):
    def test_epoch_milliseconds_and_iso_strings_for_the_same_instant_match(self):
        self.assertEqual(normalize_time(START_MS), START)
        self.assertEqual(normalize_time(float(START_MS)), START)
        self.assertEqual(normalize_time(str(START_MS)), START)
        self.assertEqual(normalize_time(START), START)

    def test_an_offset_is_converted_to_utc(self):
        self.assertEqual(normalize_time("2026-10-13T13:34:47.476-05:00"), START)

    def test_a_time_without_a_zone_is_refused_because_it_could_mean_two_instants(self):
        with self.assertRaisesRegex(TicketError, "no time zone"):
            normalize_time("2026-10-13T13:34:47.476")

    def test_missing_and_nonsense_times_are_refused(self):
        for bad in (None, True, "", "yesterday", [1], {}, 1e30):
            with self.assertRaises(TicketError, msg=repr(bad)):
                normalize_time(bad)


class TicketStoreTests(unittest.TestCase):
    def setUp(self):
        self.moment = datetime(2026, 10, 13, 18, 35, 0, tzinfo=timezone.utc)
        self.store = TicketStore(clock=lambda: self.moment)
        self.addCleanup(self.store.close)

    def test_a_ticket_is_created_with_defaults_and_the_stores_clock(self):
        ticket, created = self.store.create(BODY)
        self.assertTrue(created)
        self.assertEqual(ticket, {"id": 1, "created_at": "2026-10-13T18:35:00.000Z", "site": "site1", "equipment": "Inv1",
                                  "fault_started_at": START, "priority": "High", "summary": "Fault on site1 Inv1",
                                  "status": "open"})

    def test_the_same_fault_sent_twice_is_one_ticket(self):
        first, created_first = self.store.create(BODY)
        self.moment = datetime(2026, 10, 13, 18, 36, 0, tzinfo=timezone.utc)
        second, created_second = self.store.create(dict(BODY, summary="a retry with different text"))
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(second, first)  # the original, untouched
        self.assertEqual(self.store.count(), 1)

    def test_a_duplicate_does_not_use_up_a_ticket_number(self):
        self.store.create(BODY)
        self.store.create(BODY)
        self.store.create(BODY)
        ticket, _ = self.store.create(dict(BODY, equipment="Inv2"))
        self.assertEqual(ticket["id"], 2)

    def test_the_same_instant_in_another_format_is_still_the_same_fault(self):
        self.store.create(BODY)
        _, created = self.store.create(dict(BODY, fault_started_at=START_MS))
        self.assertFalse(created)

    def test_another_site_inverter_or_start_time_is_a_new_ticket(self):
        self.store.create(BODY)
        for change in ({"site": "site2"}, {"equipment": "Inv2"}, {"fault_started_at": "2026-10-13T18:40:00Z"}):
            _, created = self.store.create(dict(BODY, **change))
            self.assertTrue(created, change)
        self.assertEqual(self.store.count(), 4)

    def test_text_fields_are_trimmed(self):
        ticket, _ = self.store.create({"site": " site1 ", "equipment": "Inv1\n", "fault_started_at": START, "summary": " Inverter fault "})
        self.assertEqual((ticket["site"], ticket["equipment"], ticket["summary"]), ("site1", "Inv1", "Inverter fault"))

    def test_a_request_the_store_cannot_use_is_refused_with_a_reason(self):
        cases = [("body is not an object", ["not", "an", "object"], "JSON object"),
                 ("no site", {"equipment": "Inv1", "fault_started_at": START}, "site is required"),
                 ("blank equipment", dict(BODY, equipment="  "), "equipment is required"),
                 ("site not text", dict(BODY, site=5), "site is required"),
                 ("no start time", {"site": "site1", "equipment": "Inv1"}, "fault_started_at is required"),
                 ("unknown priority", dict(BODY, priority="Urgent"), "priority 'Urgent' is not one of"),
                 ("too long", dict(BODY, summary="x" * 201), "longer than 200")]
        for label, body, reason in cases:
            with self.subTest(label), self.assertRaisesRegex(TicketError, reason):
                self.store.create(body)
        self.assertEqual(self.store.count(), 0)

    def test_every_priority_of_the_scheme_is_accepted(self):
        for index, priority in enumerate(("Diagnostic", "Low", "Medium", "High", "Critical")):
            ticket, _ = self.store.create(dict(BODY, equipment="Inv%d" % index, priority=priority))
            self.assertEqual(ticket["priority"], priority)

    def test_listing_is_newest_first_and_get_finds_one_or_none(self):
        for number in (1, 2, 3):
            self.store.create(dict(BODY, equipment="Inv%d" % number))
        self.assertEqual([t["equipment"] for t in self.store.list()], ["Inv3", "Inv2", "Inv1"])
        self.assertEqual(self.store.get(2)["equipment"], "Inv2")
        self.assertIsNone(self.store.get(99))

    def test_tickets_and_the_duplicate_rule_survive_reopening_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "cmms.sqlite3")
            first = TicketStore(path)
            first.create(BODY)
            first.close()
            second = TicketStore(path)
            try:
                self.assertEqual(second.count(), 1)
                _, created = second.create(BODY)
                self.assertFalse(created)
            finally:
                second.close()  # Windows cannot delete the folder while a connection is open


if __name__ == "__main__":
    unittest.main()
