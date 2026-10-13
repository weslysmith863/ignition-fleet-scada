"""Tests for the battery in sim.model and sim.plant_controller (ADR 0016): power, state of charge, losses, limits, and control."""
import math
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from sim.model import PlantModel, SiteConfig
from sim.modbus_server import Simulation
from sim.plant_controller import PlantController

NOON_JUNE = datetime(2026, 6, 21, 18, 50, tzinfo=timezone.utc)  # clear-sky solar noon: the plant clips at 5 MW
MID_MORNING = NOON_JUNE.replace(hour=14, minute=0)  # sun well up, PV output about 1.9 MW of the 5 MW rating
LATE_AFTERNOON = NOON_JUNE.replace(hour=16, minute=0)  # PV output about 4.35 MW
NIGHT = datetime(2026, 6, 21, 6, 0, tzinfo=timezone.utc)
BATTERY = SiteConfig(clouds_enabled=False, battery_w=2.5e6, battery_wh=10.0e6)
ETA = math.sqrt(0.85)  # the loss is split evenly between charging and discharging


def run(model, when, seconds, step_s):
    state = None
    for _ in range(int(seconds / step_s)):
        state = model.step(when, step_s)
    return state


class BatteryModelTests(unittest.TestCase):
    def test_a_plant_without_a_battery_is_unchanged(self):
        model = PlantModel(SiteConfig(clouds_enabled=False))
        model.set_battery("Discharge", 2.0)
        state = model.step(NIGHT, 1.0)
        self.assertEqual((state["battery_w"], state["battery_soc"]), (0.0, 0.0))
        self.assertEqual(state["poi_w"], state["pv_w"])

    def test_the_battery_starts_idle_at_half_charge(self):
        state = PlantModel(BATTERY).step(NIGHT, 1.0)
        self.assertEqual((state["battery_mode"], state["battery_w"]), ("Idle", 0.0))
        self.assertAlmostEqual(state["battery_soc"], 0.5)

    def test_an_idle_battery_holds_its_charge(self):
        state = run(PlantModel(BATTERY), NIGHT, 3600, 60)
        self.assertAlmostEqual(state["battery_soc"], 0.5)

    def test_discharging_at_night_exports_the_setpoint_and_lowers_the_charge(self):
        model = PlantModel(BATTERY)
        model.set_battery("Discharge", 2.0)
        state = model.step(NIGHT, 1.0)
        self.assertAlmostEqual(state["battery_w"], 2.0e6)
        self.assertAlmostEqual(state["poi_w"], 2.0e6)  # no PV at night, so the meter sees the battery alone
        self.assertLess(state["battery_soc"], 0.5)

    def test_one_hour_at_full_power_takes_the_losses_out_of_the_store(self):
        model = PlantModel(BATTERY)
        model.set_battery("Discharge", 2.5)
        state = run(model, NIGHT, 3600, 60)
        # 2.5 MWh delivered cost 2.5 / sqrt(0.85) MWh from the store, out of 10 MWh nameplate
        self.assertAlmostEqual(state["battery_soc"], 0.5 - 2.5 / ETA / 10.0, places=4)

    def test_the_round_trip_returns_85_percent_of_the_energy(self):
        model = PlantModel(BATTERY)
        model.set_battery("Charge", 1.0)
        charged = model.step(NIGHT, 3600.0)  # one hour at 1 MW taken from the bus
        self.assertAlmostEqual(charged["battery_w"], -1.0e6)
        model.set_battery("Discharge", 1.0)
        out = model.step(NIGHT, 3600.0 * 0.85)  # the 0.85 MWh that comes back at 1 MW
        self.assertAlmostEqual(out["battery_stored_wh"], 5.0e6, delta=1.0)  # the store is back where it began
        self.assertAlmostEqual(out["battery_discharged_wh"] / 1.0e6, 0.85, places=6)

    def test_charging_draws_from_the_grid_when_there_is_no_sun_and_the_meter_counts_the_import(self):
        model = PlantModel(BATTERY)
        model.set_battery("Charge", 1.0)
        state = model.step(NIGHT, 3600.0)
        self.assertAlmostEqual(state["poi_w"], -1.0e6)
        self.assertAlmostEqual(state["energy_import_wh"], 1.0e6)
        self.assertEqual(state["energy_wh"], 0.0)

    def test_export_is_held_at_the_plant_rating_so_a_full_sun_noon_leaves_no_room_to_discharge(self):
        model = PlantModel(BATTERY)
        model.set_battery("Discharge", 2.5)
        state = model.step(NOON_JUNE, 1.0)
        self.assertAlmostEqual(state["pv_w"], 5.0e6, delta=4.0)
        self.assertAlmostEqual(state["battery_w"], 0.0, delta=4.0)
        self.assertAlmostEqual(state["poi_w"], 5.0e6, delta=4.0)

    def test_a_discharge_fills_only_the_room_left_under_the_rating(self):
        model = PlantModel(BATTERY)
        model.set_battery("Discharge", 2.5)
        state = model.step(LATE_AFTERNOON, 1.0)  # PV about 4.35 MW, so only about 0.65 MW of room
        room = 5.0e6 - state["pv_w"]
        self.assertTrue(0.0 < room < 2.5e6)
        self.assertAlmostEqual(state["battery_w"], room, delta=4.0)
        self.assertAlmostEqual(state["poi_w"], 5.0e6, delta=4.0)

    def test_with_enough_room_the_battery_delivers_its_whole_setpoint_on_top_of_the_sun(self):
        model = PlantModel(BATTERY)
        model.set_battery("Discharge", 2.5)
        state = model.step(MID_MORNING, 1.0)  # PV about 1.9 MW, room about 3.1 MW
        self.assertAlmostEqual(state["battery_w"], 2.5e6, delta=1.0)
        self.assertAlmostEqual(state["poi_w"], state["pv_w"] + 2.5e6, delta=1.0)

    def test_an_enabled_limit_also_caps_the_export_so_the_battery_adds_nothing_above_it(self):
        model = PlantModel(BATTERY)
        model.set_limit(3.0, True)
        model.set_battery("Discharge", 2.5)
        state = model.step(NOON_JUNE, 1.0)
        self.assertAlmostEqual(state["pv_w"], 3.0e6, delta=1.0)
        self.assertAlmostEqual(state["battery_w"], 0.0, delta=1.0)
        self.assertTrue(state["limit_binding"])

    def test_the_battery_can_charge_while_the_sun_is_up_and_the_meter_shows_the_difference(self):
        model = PlantModel(BATTERY)
        model.set_battery("Charge", 2.0)
        state = model.step(NOON_JUNE, 1.0)
        self.assertAlmostEqual(state["poi_w"], state["pv_w"] - 2.0e6, delta=4.0)

    def test_power_fades_in_a_straight_line_to_zero_at_the_low_limit(self):
        for soc, share in ((0.20, 1.0), (0.15, 0.5), (0.10, 0.0), (0.12, 0.2)):
            model = PlantModel(replace(BATTERY, battery_soc_start=soc))
            model.set_battery("Discharge", 2.5)
            state = model.step(NIGHT, 1.0)
            self.assertAlmostEqual(state["battery_w"], 2.5e6 * share, delta=1.0, msg="soc %.2f" % soc)

    def test_power_fades_in_a_straight_line_to_zero_at_the_high_limit(self):
        for soc, share in ((0.80, 1.0), (0.85, 0.5), (0.90, 0.0)):
            model = PlantModel(replace(BATTERY, battery_soc_start=soc))
            model.set_battery("Charge", 2.5)
            state = model.step(NIGHT, 1.0)
            self.assertAlmostEqual(-state["battery_w"], 2.5e6 * share, delta=1.0, msg="soc %.2f" % soc)

    def test_one_long_step_cannot_carry_the_charge_past_a_limit(self):
        model = PlantModel(BATTERY)
        model.set_battery("Discharge", 2.5)
        state = model.step(NIGHT, 3600.0 * 10)
        self.assertAlmostEqual(state["battery_stored_wh"], 1.0e6, delta=1.0)  # 10 percent of the nameplate
        model = PlantModel(BATTERY)
        model.set_battery("Charge", 2.5)
        state = model.step(NIGHT, 3600.0 * 10)
        self.assertAlmostEqual(state["battery_stored_wh"], 9.0e6, delta=1.0)

    def test_a_long_discharge_never_goes_below_the_low_limit(self):
        model = PlantModel(BATTERY)
        model.set_battery("Discharge", 2.5)
        state = run(model, NIGHT, 3600 * 6, 30)
        self.assertGreaterEqual(state["battery_soc"], 0.10 - 1e-9)
        self.assertLess(state["battery_soc"], 0.12)  # it has effectively emptied to its limit

    def test_the_setpoint_is_held_between_zero_and_the_rating_and_bad_values_are_ignored(self):
        model = PlantModel(BATTERY)
        self.assertEqual(model.set_battery("Charge", 99.0), ("Charge", 2.5))
        self.assertEqual(model.set_battery("Charge", -3.0), ("Charge", 0.0))
        model.set_battery("Discharge", 1.5)
        for bad_mode in ("discharge", "Fast", None, 1):
            self.assertEqual(model.set_battery(bad_mode, 1.5), ("Discharge", 1.5))
        for bad_setpoint in (float("nan"), float("inf"), "2", None, True):
            self.assertEqual(model.set_battery("Discharge", bad_setpoint), ("Discharge", 1.5))

    def test_a_restart_resets_the_battery_to_half_charge_and_idle(self):
        model = PlantModel(BATTERY)
        model.set_battery("Discharge", 2.5)
        run(model, NIGHT, 600, 60)
        fresh = PlantModel(BATTERY).step(NIGHT, 1.0)
        self.assertEqual(fresh["battery_mode"], "Idle")
        self.assertAlmostEqual(fresh["battery_soc"], 0.5)


def make(config, when):
    simulation = Simulation(config, noise=False)
    simulation.tick(when, 1.0)
    return simulation, PlantController(simulation)


class BatteryControllerTests(unittest.TestCase):
    def test_a_plant_with_a_battery_has_two_more_nodes(self):
        _, controller = make(BATTERY, NIGHT)
        nodes = controller.readings()
        self.assertEqual(set(nodes) - {"ActivePowerLimit_MW", "LimitEnable", "LimitActive", "POI_MW", "Status", "RatedMW", "TripInverter"},
                         {"BatteryMode", "BatterySetpoint_MW"})
        self.assertEqual((nodes["BatteryMode"], nodes["BatterySetpoint_MW"]), ("Idle", 0.0))

    def test_a_plant_without_one_has_neither_and_ignores_a_battery_command(self):
        _, controller = make(SiteConfig(clouds_enabled=False), NIGHT)
        self.assertFalse({"BatteryMode", "BatterySetpoint_MW"} & set(controller.readings()))
        self.assertEqual(controller.command_battery("Discharge", 2.0), ("Idle", 0.0))

    def test_a_battery_command_reaches_the_plant_on_the_next_tick_and_shows_in_poi(self):
        simulation, controller = make(BATTERY, NIGHT)
        self.assertEqual(controller.command_battery("Discharge", 2.0), ("Discharge", 2.0))
        self.assertEqual(controller.readings()["POI_MW"], 0.0)  # nothing changes until the model steps
        simulation.tick(NIGHT, 1.0)
        nodes = controller.readings()
        self.assertAlmostEqual(nodes["POI_MW"], 2.0, places=6)
        self.assertEqual((nodes["BatteryMode"], nodes["BatterySetpoint_MW"]), ("Discharge", 2.0))
        self.assertEqual(nodes["Status"], "Producing")

    def test_the_rating_stays_the_pv_nameplate(self):
        simulation, controller = make(BATTERY, NIGHT)
        controller.command_battery("Discharge", 2.5)
        simulation.tick(NIGHT, 1.0)
        self.assertEqual(controller.readings()["RatedMW"], 5.0)

    def test_the_accepted_values_are_returned_so_the_server_can_write_them_back(self):
        _, controller = make(BATTERY, NIGHT)
        self.assertEqual(controller.command_battery("Charge", 40.0), ("Charge", 2.5))
        self.assertEqual(controller.command_battery("Nonsense", 1.0), ("Charge", 1.0))


if __name__ == "__main__":
    unittest.main()
