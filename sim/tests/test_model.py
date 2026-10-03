"""Tests for sim.model: the assembled chain for Site 1 (ADR 0006 and 0008)."""
import unittest
from datetime import datetime, timedelta, timezone

from sim.model import PlantModel, SiteConfig

NOON_JUNE = datetime(2026, 6, 21, 18, 50, tzinfo=timezone.utc)  # clear-sky solar noon at the site
NIGHT = datetime(2026, 6, 21, 6, 0, tzinfo=timezone.utc)  # about 01:00 local
CLEAR = SiteConfig(clouds_enabled=False)
RATED_PLANT_W = 4 * 1.25e6


class PlantModelTests(unittest.TestCase):
    def test_no_output_at_night(self):
        state = PlantModel(CLEAR).step(NIGHT, 1.0)
        self.assertEqual(state["poa_w_m2"], 0.0)
        self.assertEqual(state["poi_w"], 0.0)
        self.assertEqual(state["inverter_dc_w"], [0.0] * 4)

    def test_clear_summer_noon_clips_at_the_plant_ac_rating(self):
        state = PlantModel(CLEAR).step(NOON_JUNE, 1.0)
        self.assertGreater(state["poa_w_m2"], 900.0)
        # DC power offered by the modules exceeds what the inverter can pass, so every inverter sits at its rating
        self.assertGreater(state["inverter_dc_w"][0] * 0.96, 1.25e6)
        for ac in state["inverter_ac_w"]:
            self.assertAlmostEqual(ac, 1.25e6, delta=1.0)
        self.assertAlmostEqual(state["poi_w"], RATED_PLANT_W, delta=4.0)

    def test_output_below_the_rating_is_not_clipped(self):
        state = PlantModel(CLEAR).step(NOON_JUNE.replace(hour=14, minute=0), 1.0)  # mid-morning, sun well up
        self.assertGreater(state["poi_w"], 0.0)
        self.assertLess(state["poi_w"], RATED_PLANT_W)

    def test_a_limit_below_the_available_power_caps_the_plant_exactly(self):
        model = PlantModel(CLEAR)
        model.set_limit(3.0, True)
        state = model.step(NOON_JUNE, 1.0)
        self.assertAlmostEqual(state["poi_w"], 3.0e6, delta=1.0)
        self.assertTrue(state["limit_binding"])
        self.assertAlmostEqual(state["inverter_ac_w"][0], 0.75e6, delta=1.0)  # shared out equally for identical inverters

    def test_a_disabled_limit_does_nothing(self):
        model = PlantModel(CLEAR)
        model.set_limit(3.0, False)
        state = model.step(NOON_JUNE, 1.0)
        self.assertAlmostEqual(state["poi_w"], RATED_PLANT_W, delta=4.0)
        self.assertFalse(state["limit_binding"])

    def test_a_limit_above_the_available_power_is_not_binding(self):
        model = PlantModel(CLEAR)
        model.set_limit(8.0, True)
        state = model.step(NOON_JUNE, 1.0)
        self.assertFalse(state["limit_binding"])
        self.assertAlmostEqual(state["poi_w"], RATED_PLANT_W, delta=4.0)

    def test_clipping_and_curtailment_look_different(self):
        # The case from Q8: at the AC rating with no limit is clipping; below the rating with a limit is curtailment.
        clipped = PlantModel(CLEAR).step(NOON_JUNE, 1.0)
        model = PlantModel(CLEAR)
        model.set_limit(3.0, True)
        curtailed = model.step(NOON_JUNE, 1.0)
        self.assertAlmostEqual(clipped["poi_w"], RATED_PLANT_W, delta=4.0)
        self.assertFalse(clipped["limit_binding"])
        self.assertLess(curtailed["poi_w"], RATED_PLANT_W)
        self.assertTrue(curtailed["limit_binding"])

    def test_energy_accumulates_in_watt_hours(self):
        model = PlantModel(CLEAR)
        state = model.step(NOON_JUNE, 3600.0)  # one hour at the noon value
        self.assertAlmostEqual(state["energy_wh"], state["poi_w"], delta=1.0)
        state = model.step(NOON_JUNE, 1800.0)
        self.assertAlmostEqual(state["energy_wh"], state["poi_w"] * 1.5, delta=2.0)

    def test_winter_noon_has_less_horizontal_sunlight_but_the_plant_still_produces(self):
        # Compare GHI, not POA: a south-facing panel tilted near the latitude can see more light in winter than in summer.
        winter = PlantModel(CLEAR).step(NOON_JUNE.replace(month=12), 1.0)
        summer = PlantModel(CLEAR).step(NOON_JUNE, 1.0)
        self.assertLess(winter["ghi_w_m2"], summer["ghi_w_m2"])
        self.assertGreater(winter["poi_w"], 0.0)

    def test_the_same_seed_gives_the_same_day(self):
        def day(seed):
            model = PlantModel(SiteConfig(seed=seed))
            t = NOON_JUNE - timedelta(hours=1)
            out = []
            for _ in range(600):
                t += timedelta(seconds=5)
                out.append(round(model.step(t, 5.0)["poi_w"], 3))
            return out
        self.assertEqual(day(3), day(3))
        self.assertNotEqual(day(3), day(4))


if __name__ == "__main__":
    unittest.main()
