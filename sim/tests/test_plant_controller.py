"""Tests for sim.plant_controller: the five plant controller nodes and how a written limit reaches the plant model."""
import unittest
from datetime import datetime, timezone

from sim.model import SiteConfig
from sim.modbus_server import Simulation
from sim.plant_controller import PlantController

NOON_JUNE = datetime(2026, 6, 21, 18, 50, tzinfo=timezone.utc)  # clear-sky solar noon: the plant is clipping at 5 MW
MID_MORNING = NOON_JUNE.replace(hour=14, minute=0)  # sun well up, output below the rating
NIGHT = datetime(2026, 6, 21, 6, 0, tzinfo=timezone.utc)


def make(when):
    simulation = Simulation(SiteConfig(clouds_enabled=False), noise=False)
    simulation.tick(when, 1.0)
    return simulation, PlantController(simulation)


class PlantControllerTests(unittest.TestCase):
    def test_the_rating_follows_the_inverter_count(self):
        simulation = Simulation(SiteConfig(clouds_enabled=False, inverters=6), noise=False)
        simulation.tick(NOON_JUNE, 1.0)
        controller = PlantController(simulation)
        nodes = controller.readings()
        self.assertEqual(nodes["ActivePowerLimit_MW"], 7.5)
        self.assertAlmostEqual(nodes["POI_MW"], 7.5, places=3)

    def test_an_untouched_controller_reports_the_plant_unrestricted(self):
        _, controller = make(NOON_JUNE)
        nodes = controller.readings()
        self.assertEqual(set(nodes), {"ActivePowerLimit_MW", "LimitEnable", "LimitActive", "POI_MW", "Status"})
        self.assertEqual(nodes["ActivePowerLimit_MW"], 5.0)
        self.assertFalse(nodes["LimitEnable"])
        self.assertFalse(nodes["LimitActive"])
        self.assertAlmostEqual(nodes["POI_MW"], 5.0, places=3)
        self.assertEqual(nodes["Status"], "Producing")

    def test_an_enabled_limit_curtails_the_plant_on_the_next_tick(self):
        simulation, controller = make(NOON_JUNE)
        controller.command(3.0, True)
        self.assertAlmostEqual(controller.readings()["POI_MW"], 5.0, places=3)  # nothing changes until the model steps
        simulation.tick(NOON_JUNE, 1.0)
        nodes = controller.readings()
        self.assertAlmostEqual(nodes["POI_MW"], 3.0, places=3)
        self.assertTrue(nodes["LimitActive"])
        self.assertEqual(nodes["Status"], "Curtailed")

    def test_a_limit_that_is_not_enabled_does_nothing(self):
        simulation, controller = make(NOON_JUNE)
        controller.command(1.0, False)
        simulation.tick(NOON_JUNE, 1.0)
        nodes = controller.readings()
        self.assertAlmostEqual(nodes["POI_MW"], 5.0, places=3)
        self.assertFalse(nodes["LimitActive"])
        self.assertEqual(nodes["ActivePowerLimit_MW"], 1.0)  # the written value is kept, just not applied

    def test_an_enabled_limit_above_the_available_power_is_not_active(self):
        # Curtailment is a limit that bites. A cap above what the plant could make anyway leaves output unchanged.
        simulation, controller = make(MID_MORNING)
        available = controller.readings()["POI_MW"]
        self.assertTrue(0.5 < available < 4.9)
        controller.command(4.9, True)
        simulation.tick(MID_MORNING, 1.0)
        nodes = controller.readings()
        self.assertAlmostEqual(nodes["POI_MW"], available, places=6)
        self.assertTrue(nodes["LimitEnable"])
        self.assertFalse(nodes["LimitActive"])
        self.assertEqual(nodes["Status"], "Producing")

    def test_removing_the_limit_restores_full_output(self):
        simulation, controller = make(NOON_JUNE)
        controller.command(2.0, True)
        simulation.tick(NOON_JUNE, 1.0)
        controller.command(2.0, False)
        simulation.tick(NOON_JUNE, 1.0)
        nodes = controller.readings()
        self.assertAlmostEqual(nodes["POI_MW"], 5.0, places=3)
        self.assertFalse(nodes["LimitActive"])

    def test_the_limit_is_held_between_zero_and_the_plant_rating(self):
        _, controller = make(NOON_JUNE)
        self.assertEqual(controller.command(99.0, True), (5.0, True))
        self.assertEqual(controller.command(-2.0, True), (0.0, True))

    def test_a_value_that_is_not_a_finite_number_leaves_the_limit_alone(self):
        _, controller = make(NOON_JUNE)
        controller.command(3.0, True)
        for bad in (float("nan"), float("inf"), "3", None, True):
            self.assertEqual(controller.command(bad, True), (3.0, True))

    def test_a_zero_limit_stops_output_and_reads_as_curtailed(self):
        simulation, controller = make(NOON_JUNE)
        controller.command(0.0, True)
        simulation.tick(NOON_JUNE, 1.0)
        nodes = controller.readings()
        self.assertEqual(nodes["POI_MW"], 0.0)
        self.assertEqual(nodes["Status"], "Curtailed")

    def test_standby_at_night(self):
        _, controller = make(NIGHT)
        nodes = controller.readings()
        self.assertEqual(nodes["POI_MW"], 0.0)
        self.assertEqual(nodes["Status"], "Standby")
        self.assertFalse(nodes["LimitActive"])


if __name__ == "__main__":
    unittest.main()
