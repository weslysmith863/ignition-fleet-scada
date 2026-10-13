import unittest

from cmms.page import render_page

TICKET = {"id": 7, "created_at": "2026-10-13T18:35:00.000Z", "site": "site1", "equipment": "Inv1",
          "fault_started_at": "2026-10-13T18:34:47.476Z", "priority": "High", "status": "open", "summary": "Inverter fault"}


class PageTests(unittest.TestCase):
    def test_an_empty_list_says_so(self):
        page = render_page([])
        self.assertIn("No tickets yet.", page)
        self.assertNotIn("<table>", page)

    def test_each_ticket_is_a_row_with_every_column(self):
        page = render_page([TICKET])
        self.assertEqual(page.count("<tr>"), 2)  # the header and one ticket
        for value in TICKET.values():
            self.assertIn(">%s<" % value, page)

    def test_text_from_a_sender_is_escaped(self):
        page = render_page([dict(TICKET, summary="<script>alert(1)</script> & more")])
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; more", page)

    def test_the_page_refreshes_itself(self):
        self.assertIn('http-equiv="refresh"', render_page([]))


if __name__ == "__main__":
    unittest.main()
