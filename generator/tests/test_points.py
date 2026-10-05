"""Tests for generator.points: reading and checking the points list."""
import pathlib
import tempfile
import unittest

from generator.points import PointsError, read_points

REAL_LIST = pathlib.Path(__file__).resolve().parents[2] / "points" / "site1.csv"
HEADER = "site,device,kind,unit_id,host,port,rated_kw\n"


def read_text(text):
    with tempfile.TemporaryDirectory() as folder:
        path = pathlib.Path(folder) / "points.csv"
        path.write_text(text, encoding="utf-8", newline="\n")
        return read_points(path)


class PointsTests(unittest.TestCase):
    def test_the_real_site_one_list_has_four_inverters_a_weather_station_and_a_meter_on_units_one_to_six(self):
        rows = read_points(REAL_LIST)
        self.assertEqual([r.device for r in rows], ["Inv1", "Inv2", "Inv3", "Inv4", "Weather", "Meter"])
        self.assertEqual([r.unit_id for r in rows], [1, 2, 3, 4, 5, 6])
        inverters = rows[:4]
        self.assertTrue(all(r.kind == "inverter" and r.udt == "Inverter" and r.folder == "Inverters" for r in inverters))
        self.assertEqual({(r.host, r.port, r.rated_kw) for r in inverters}, {("host.docker.internal", 15020, 1250.0)})
        self.assertEqual([(r.udt, r.rated_kw, r.tag_path) for r in rows[4:]], [("Weather", None, "Weather"), ("Meter", None, "Meter")])

    def test_an_inverter_is_found_in_its_folder_and_a_weather_station_at_the_tag_root(self):
        rows = read_text(HEADER + "site1,Inv1,inverter,1,h,15020,1250\nsite1,Weather,weather,5,h,15020,\n")
        self.assertEqual([r.tag_path for r in rows], ["Inverters/Inv1", "Weather"])

    def test_a_wrong_header_is_rejected(self):
        with self.assertRaisesRegex(PointsError, "header"):
            read_text("site,device\nsite1,Inv1\n")

    def test_an_unknown_kind_is_rejected_with_its_line_number(self):
        with self.assertRaisesRegex(PointsError, "line 2.*kind"):
            read_text(HEADER + "site1,Inv1,toaster,1,h,15020,1250\n")

    def test_numbers_must_be_numbers(self):
        with self.assertRaisesRegex(PointsError, "line 2"):
            read_text(HEADER + "site1,Inv1,inverter,one,h,15020,1250\n")

    def test_unit_id_and_port_ranges_are_enforced(self):
        with self.assertRaisesRegex(PointsError, "unit_id"):
            read_text(HEADER + "site1,Inv1,inverter,0,h,15020,1250\n")
        with self.assertRaisesRegex(PointsError, "unit_id"):
            read_text(HEADER + "site1,Inv1,inverter,248,h,15020,1250\n")
        with self.assertRaisesRegex(PointsError, "port"):
            read_text(HEADER + "site1,Inv1,inverter,1,h,70000,1250\n")

    def test_rated_power_must_be_positive(self):
        with self.assertRaisesRegex(PointsError, "rated_kw"):
            read_text(HEADER + "site1,Inv1,inverter,1,h,15020,0\n")

    def test_an_inverter_needs_a_rating_and_a_weather_station_must_not_have_one(self):
        with self.assertRaisesRegex(PointsError, "line 2.*rated_kw must be a number"):
            read_text(HEADER + "site1,Inv1,inverter,1,h,15020,\n")
        with self.assertRaisesRegex(PointsError, "line 2.*rated_kw must be empty for kind weather"):
            read_text(HEADER + "site1,Weather,weather,5,h,15020,1250\n")

    def test_an_empty_field_is_rejected(self):
        with self.assertRaisesRegex(PointsError, "host is empty"):
            read_text(HEADER + "site1,Inv1,inverter,1,,15020,1250\n")

    def test_device_names_must_be_plain(self):
        with self.assertRaisesRegex(PointsError, "plain name"):
            read_text(HEADER + "site1,Inv 1,inverter,1,h,15020,1250\n")

    def test_duplicate_names_are_rejected(self):
        with self.assertRaisesRegex(PointsError, "twice"):
            read_text(HEADER + "site1,Inv1,inverter,1,h,15020,1250\nsite1,Inv1,inverter,2,h,15020,1250\n")

    def test_two_devices_cannot_share_host_port_and_unit_id(self):
        with self.assertRaisesRegex(PointsError, "same host, port, and unit ID"):
            read_text(HEADER + "site1,Inv1,inverter,1,h,15020,1250\nsite1,Inv2,inverter,1,h,15020,1250\n")

    def test_the_same_unit_id_on_different_hosts_is_fine(self):
        rows = read_text(HEADER + "site1,Inv1,inverter,1,a,15020,1250\nsite1,Inv2,inverter,1,b,15020,1250\n")
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
