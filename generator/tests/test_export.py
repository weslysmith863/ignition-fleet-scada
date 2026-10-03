"""Tests for generator.export_types: the saved file must be stable so Git diffs show real changes only."""
import json
import unittest

from generator.export_types import normalize, render

EXPORT_A = {
    "name": "_types_", "tagType": "Folder",
    "tags": [
        {"name": "Weather", "tagType": "UdtType", "tags": [{"name": "b", "tagType": "AtomicTag"}, {"name": "A", "tagType": "AtomicTag"}]},
        {"name": "Inverter", "tagType": "UdtType", "parameters": {"UnitId": {"dataType": "Integer"}, "Device": {"dataType": "String"}}},
    ],
}
# The same content as the gateway might return it on another day: members in a different order.
EXPORT_B = {
    "tags": [
        {"tagType": "UdtType", "parameters": {"Device": {"dataType": "String"}, "UnitId": {"dataType": "Integer"}}, "name": "Inverter"},
        {"tags": [{"tagType": "AtomicTag", "name": "A"}, {"tagType": "AtomicTag", "name": "b"}], "tagType": "UdtType", "name": "Weather"},
    ],
    "tagType": "Folder", "name": "_types_",
}


class ExportTests(unittest.TestCase):
    def test_the_same_content_in_a_different_order_renders_identically(self):
        self.assertEqual(render(EXPORT_A), render(EXPORT_B))

    def test_members_are_sorted_by_name_ignoring_case(self):
        names = [t["name"] for t in normalize(EXPORT_A)["tags"]]
        self.assertEqual(names, ["Inverter", "Weather"])
        weather = next(t for t in normalize(EXPORT_A)["tags"] if t["name"] == "Weather")
        self.assertEqual([t["name"] for t in weather["tags"]], ["A", "b"])

    def test_the_text_is_lf_only_ends_with_one_newline_and_round_trips(self):
        text = render(EXPORT_A)
        self.assertNotIn("\r", text)
        self.assertTrue(text.endswith("}\n") and not text.endswith("\n\n"))
        self.assertEqual(json.loads(text), normalize(EXPORT_A))

    def test_normalizing_does_not_change_the_input(self):
        before = json.dumps(EXPORT_A, sort_keys=True)
        normalize(EXPORT_A)
        self.assertEqual(json.dumps(EXPORT_A, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
