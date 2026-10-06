"""Tests for generator.import_types against an in-memory fake gateway: create missing types, never overwrite, report drift."""
import copy
import pathlib
import unittest

from generator import import_types
from generator.gateway import GatewayError
from generator.import_types import TypesError

SAVED = pathlib.Path(__file__).resolve().parents[2] / "gateway" / "site1" / "udt-types.json"
WANTED = import_types.load_types(SAVED)


class FakeGateway:
    """Holds UDT definitions under _types_. An empty provider answers the export with tagType Unknown, as the real one does."""

    def __init__(self, types=(), empty_answer="Unknown"):
        self.types = {t["name"]: copy.deepcopy(t) for t in types}
        self.imports = []
        self.empty_answer = empty_answer  # a fresh provider answers with an empty Folder; a missing path answers Unknown

    def export_tags(self, path):
        assert path == "_types_"
        if not self.types:
            return {"name": "_types_", "tagType": self.empty_answer}
        return {"name": "_types_", "tagType": "Folder", "tags": [copy.deepcopy(t) for t in self.types.values()]}

    def import_tags(self, payload, path=None, policy="Abort"):
        self.imports.append((path, copy.deepcopy(payload), policy))
        for item in payload["tags"]:
            if policy == "Abort" and item["name"] in self.types:
                raise GatewayError("collision on %s" % item["name"])
            self.types[item["name"]] = copy.deepcopy(item)  # "Overwrite" replaces the whole definition


class NormalizingGateway(FakeGateway):
    """A gateway that stores a type slightly differently from how it was sent, as Designer did with data types (finding 22)."""

    def import_tags(self, payload, path=None, policy="Abort"):
        super().import_tags(payload, path, policy)
        for item in payload["tags"]:
            stored = copy.deepcopy(item)  # never change what the caller passed: it is the same object as the file's side
            stored["tags"][0]["dataType"] = "NotWhatWasSent"
            self.types[item["name"]] = stored


def by_name(name):
    return next(t for t in WANTED if t["name"] == name)


class LoadTests(unittest.TestCase):
    def test_the_saved_file_holds_the_four_phase_1_types(self):
        self.assertEqual(sorted(t["name"] for t in WANTED), ["Inverter", "Meter", "PlantController", "Weather"])

    def test_a_file_that_is_not_the_types_folder_is_refused(self):
        with self.assertRaises(TypesError):
            import_types.parse_types({"name": "Inverters", "tagType": "Folder", "tags": []})

    def test_a_member_that_is_not_a_type_is_refused(self):
        with self.assertRaises(TypesError):
            import_types.parse_types({"name": "_types_", "tagType": "Folder", "tags": [{"name": "x", "tagType": "AtomicTag"}]})

    def test_a_type_that_embeds_or_extends_another_is_refused_not_mishandled(self):
        nested = {"name": "_types_", "tagType": "Folder", "tags": [
            {"name": "Site", "tagType": "UdtType", "tags": [{"name": "Inv", "tagType": "UdtInstance", "typeId": "Inverter"}]}]}
        with self.assertRaises(TypesError) as caught:
            import_types.parse_types(nested)
        self.assertIn("Site/Inv", str(caught.exception))
        self.assertIn("Inverter", str(caught.exception))


class DryRunTests(unittest.TestCase):
    def test_an_empty_provider_reports_every_type_missing_and_changes_nothing(self):
        gateway = FakeGateway()
        report = import_types.import_types(gateway, WANTED, apply=False)
        self.assertEqual(sorted(report.missing), ["Inverter", "Meter", "PlantController", "Weather"])
        self.assertEqual(report.created, [])
        self.assertEqual(gateway.imports, [])

    def test_a_fresh_provider_answers_with_an_empty_folder_and_is_handled_like_unknown(self):
        """What a real fresh provider sends (Phase 2 finding 43): a Folder with no tags key at all."""
        for answer in ("Folder", "Unknown"):
            gateway = FakeGateway(empty_answer=answer)
            report = import_types.import_types(gateway, WANTED, apply=True)
            self.assertEqual(sorted(report.created), ["Inverter", "Meter", "PlantController", "Weather"], answer)
            self.assertEqual(report.drift, [], answer)

    def test_types_that_match_are_unchanged_whatever_order_their_members_come_in(self):
        shuffled = copy.deepcopy(WANTED)
        for node in shuffled:
            node["tags"].reverse()
        gateway = FakeGateway(shuffled)
        report = import_types.import_types(gateway, WANTED, apply=True)
        self.assertEqual(sorted(report.unchanged), ["Inverter", "Meter", "PlantController", "Weather"])
        self.assertEqual((report.missing, report.drift, gateway.imports), ([], [], []))


class ApplyTests(unittest.TestCase):
    def test_apply_creates_each_missing_type_with_a_policy_that_cannot_overwrite(self):
        gateway = FakeGateway()
        report = import_types.import_types(gateway, WANTED, apply=True)
        self.assertEqual(len(gateway.imports), 4)  # one call per type, so one failure cannot hide the others
        for path, payload, policy in gateway.imports:
            self.assertEqual((path, policy), ("_types_", "Abort"))
            self.assertEqual(len(payload["tags"]), 1)
        self.assertEqual(sorted(report.created), ["Inverter", "Meter", "PlantController", "Weather"])
        self.assertEqual(report.drift, [])  # re-read after the import and found to match

    def test_apply_creates_only_what_is_missing(self):
        gateway = FakeGateway([by_name("Inverter"), by_name("Weather")])
        report = import_types.import_types(gateway, WANTED, apply=True)
        self.assertEqual(sorted(report.created), ["Meter", "PlantController"])
        self.assertEqual(sorted(report.unchanged), ["Inverter", "Weather"])
        self.assertEqual(sorted(p["tags"][0]["name"] for _, p, _ in gateway.imports), ["Meter", "PlantController"])

    def test_a_type_that_differs_is_reported_and_never_overwritten(self):
        hand_built = copy.deepcopy(by_name("Inverter"))
        hand_built["tags"][0]["expression"] = "something else"
        gateway = FakeGateway([hand_built])
        report = import_types.import_types(gateway, WANTED, apply=True)
        self.assertEqual(gateway.types["Inverter"], hand_built)  # untouched
        self.assertTrue(any(line.startswith("Inverter/") for line in report.drift))
        self.assertNotIn("Inverter", report.created + report.unchanged)
        self.assertEqual(sorted(report.created), ["Meter", "PlantController", "Weather"])  # the rest still go in

    def test_a_type_that_comes_back_different_after_the_import_is_reported(self):
        gateway = NormalizingGateway()
        report = import_types.import_types(gateway, [by_name("Weather")], apply=True)
        self.assertEqual(report.created, ["Weather"])
        self.assertTrue(report.drift)
        self.assertTrue(all(line.startswith("after import: Weather/") for line in report.drift))


class ReplaceTests(unittest.TestCase):
    """--replace NAME: the one way a type that already exists is changed, and only when it is named."""

    def hand_edited(self, name):
        node = copy.deepcopy(by_name(name))
        node["tags"].append({"name": "Extra", "tagType": "AtomicTag"})  # a member the saved file does not have
        return node

    def test_a_named_type_that_differs_is_replaced_and_read_back(self):
        gateway = FakeGateway([self.hand_edited("Inverter"), by_name("Meter"), by_name("Weather"), by_name("PlantController")])
        report = import_types.import_types(gateway, WANTED, apply=True, replace=["Inverter"])
        self.assertEqual(report.replaced, ["Inverter"])
        self.assertEqual(report.drift, [])
        self.assertEqual(gateway.types["Inverter"], by_name("Inverter"))
        self.assertEqual([(p, pol) for p, _, pol in gateway.imports], [("_types_", "Overwrite")])
        self.assertEqual(len(gateway.imports[0][1]["tags"]), 1)  # one type, never the whole folder

    def test_a_dry_run_names_the_differences_and_changes_nothing(self):
        edited = self.hand_edited("Inverter")
        gateway = FakeGateway([edited, by_name("Meter"), by_name("Weather"), by_name("PlantController")])
        report = import_types.import_types(gateway, WANTED, apply=False, replace=["Inverter"])
        self.assertEqual(list(report.replacing), ["Inverter"])
        self.assertIn("Inverter/Extra: on the gateway but not in the file", report.replacing["Inverter"])
        self.assertEqual((report.replaced, report.drift, gateway.imports), ([], [], []))
        self.assertEqual(gateway.types["Inverter"], edited)

    def test_a_type_that_differs_but_is_not_named_is_still_only_reported(self):
        gateway = FakeGateway([self.hand_edited("Inverter"), self.hand_edited("Weather"), by_name("Meter"), by_name("PlantController")])
        report = import_types.import_types(gateway, WANTED, apply=True, replace=["Inverter"])
        self.assertEqual(report.replaced, ["Inverter"])
        self.assertTrue(any(line.startswith("Weather/") for line in report.drift))
        self.assertIn("Extra", [m["name"] for m in gateway.types["Weather"]["tags"]])  # untouched

    def test_naming_a_type_that_already_matches_changes_nothing(self):
        gateway = FakeGateway(WANTED)
        report = import_types.import_types(gateway, WANTED, apply=True, replace=["Inverter"])
        self.assertEqual((report.replaced, gateway.imports), ([], []))
        self.assertIn("Inverter", report.unchanged)

    def test_naming_a_type_that_is_not_in_the_file_is_an_error(self):
        with self.assertRaises(TypesError):
            import_types.import_types(FakeGateway(), WANTED, apply=True, replace=["Nope"])

    def test_a_missing_type_is_still_created_with_abort_even_when_named(self):
        gateway = FakeGateway([by_name("Meter")])
        report = import_types.import_types(gateway, WANTED, apply=True, replace=["Inverter"])
        self.assertIn("Inverter", report.created)
        self.assertEqual({pol for _, _, pol in gateway.imports}, {"Abort"})

    def test_a_replaced_type_that_comes_back_different_is_reported(self):
        class Normalizing(NormalizingGateway):
            pass
        gateway = Normalizing([self.hand_edited("Weather")] + [by_name(n) for n in ("Inverter", "Meter", "PlantController")])
        report = import_types.import_types(gateway, WANTED, apply=True, replace=["Weather"])
        self.assertEqual(report.replaced, ["Weather"])
        self.assertTrue(all(line.startswith("after import: Weather/") for line in report.drift), report.drift)
        self.assertEqual(import_types.exit_code(report), 2)


class DriftTests(unittest.TestCase):
    def test_identical_definitions_have_no_differences(self):
        self.assertEqual(import_types.type_drift(by_name("Inverter"), copy.deepcopy(by_name("Inverter"))), [])

    def test_a_missing_an_extra_and_a_changed_member_are_each_named(self):
        found = copy.deepcopy(by_name("Inverter"))
        raw = next(m for m in found["tags"] if m["name"] == "Raw")
        raw["tags"] = [m for m in raw["tags"] if m["name"] != "W"]  # missing on the gateway
        raw["tags"].append({"name": "Extra", "tagType": "AtomicTag"})  # only on the gateway
        found["tags"][0]["dataType"] = "Float4" if found["tags"][0].get("dataType") != "Float4" else "Integer"  # changed
        problems = import_types.type_drift(by_name("Inverter"), found)
        self.assertIn("Inverter/Raw/W: missing on the gateway", problems)
        self.assertIn("Inverter/Raw/Extra: on the gateway but not in the file", problems)
        self.assertTrue(any(p.startswith("Inverter/%s: dataType is" % found["tags"][0]["name"]) for p in problems), problems)

    def test_a_parameter_difference_names_the_parameter(self):
        found = copy.deepcopy(by_name("Inverter"))
        found["parameters"]["UnitId"]["dataType"] = "String"
        problems = import_types.type_drift(by_name("Inverter"), found)
        self.assertTrue(any("parameters.UnitId" in p for p in problems), problems)


class ExitCodeTests(unittest.TestCase):
    def test_clean_means_0_and_drift_means_2(self):
        clean = import_types.import_types(FakeGateway(), WANTED, apply=True)
        self.assertEqual(import_types.exit_code(clean), 0)
        hand_built = copy.deepcopy(by_name("Meter"))
        hand_built["parameters"] = {}
        drifted = import_types.import_types(FakeGateway([hand_built]), WANTED, apply=False)
        self.assertEqual(import_types.exit_code(drifted), 2)


if __name__ == "__main__":
    unittest.main()
