"""Tests for sim.physics. Expected values are derived by hand or from geometry, not from the same formulas."""
import math
import unittest
from datetime import datetime, timezone

from sim import physics as p

LAT, LON = 31.0, -102.0


def utc(y, m, d, hh=0, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)


class SunPositionTests(unittest.TestCase):
    def test_noon_zenith_is_latitude_minus_declination_in_june(self):
        # Declination is about 23.44 degrees on 2026-06-21, so the noon zenith is about 31.0 - 23.44 = 7.56 degrees.
        sun = p.sun_position(utc(2026, 6, 21, 18, 50), LAT, LON)
        self.assertAlmostEqual(sun.zenith_deg, 7.56, delta=0.3)

    def test_noon_azimuth_is_due_south_and_solar_time_is_twelve_at_the_equinox(self):
        # Solar noon on 2026-03-20 is about 18:56 UTC at longitude -102 (equation of time about -7.6 minutes).
        sun = p.sun_position(utc(2026, 3, 20, 18, 56), LAT, LON)
        self.assertAlmostEqual(sun.azimuth_deg, 180.0, delta=3.0)
        self.assertAlmostEqual(sun.solar_time_h, 12.0, delta=0.1)
        self.assertAlmostEqual(sun.zenith_deg, LAT, delta=0.5)  # declination is near zero at the equinox

    def test_sunrise_is_in_the_east_and_sunset_in_the_west_at_the_equinox(self):
        sunrise = p.sun_position(utc(2026, 3, 20, 12, 52), LAT, LON)
        sunset = p.sun_position(utc(2026, 3, 21, 0, 59), LAT, LON)
        self.assertLess(abs(sunrise.cos_zenith), 0.03)
        self.assertAlmostEqual(sunrise.azimuth_deg, 90.0, delta=5.0)
        self.assertLess(abs(sunset.cos_zenith), 0.03)
        self.assertAlmostEqual(sunset.azimuth_deg, 270.0, delta=5.0)

    def test_the_sun_is_down_at_local_midnight(self):
        sun = p.sun_position(utc(2026, 3, 20, 6, 0), LAT, LON)
        self.assertLess(sun.cos_zenith, 0.0)
        self.assertEqual(p.haurwitz_ghi(sun.cos_zenith), 0.0)

    def test_noon_is_higher_in_summer_than_in_winter(self):
        summer = p.sun_position(utc(2026, 6, 21, 18, 50), LAT, LON)
        winter = p.sun_position(utc(2026, 12, 21, 18, 50), LAT, LON)
        self.assertGreater(summer.cos_zenith, winter.cos_zenith)
        self.assertAlmostEqual(winter.zenith_deg, 31.0 + 23.44, delta=0.5)


class IrradianceTests(unittest.TestCase):
    def test_haurwitz_with_the_sun_overhead(self):
        # 1098 x exp(-0.059) = 1035.1
        self.assertAlmostEqual(p.haurwitz_ghi(1.0), 1035.1, delta=0.1)

    def test_haurwitz_is_zero_when_the_sun_is_down(self):
        self.assertEqual(p.haurwitz_ghi(0.0), 0.0)
        self.assertEqual(p.haurwitz_ghi(-0.3), 0.0)

    def test_extraterrestrial_irradiance_is_highest_in_early_january_and_lowest_in_early_july(self):
        self.assertAlmostEqual(p.extraterrestrial_irradiance(utc(2026, 1, 3)), 1414.0, delta=4.0)
        self.assertAlmostEqual(p.extraterrestrial_irradiance(utc(2026, 7, 4)), 1320.5, delta=4.0)

    def test_erbs_low_clearness_is_almost_all_diffuse(self):
        # kt = 100 / 1000 = 0.1, diffuse fraction 1 - 0.09 x 0.1 = 0.991
        dni, dhi = p.erbs_split(100.0, 1.0, 0.0, 1000.0)
        self.assertAlmostEqual(dhi, 99.1, delta=0.01)
        self.assertAlmostEqual(dni, 0.9, delta=0.01)

    def test_erbs_middle_clearness_uses_the_polynomial(self):
        # kt = 0.5: 0.9511 - 0.0802 + 1.097 - 2.07975 + 0.771 = 0.65915
        dni, dhi = p.erbs_split(500.0, 1.0, 0.0, 1000.0)
        self.assertAlmostEqual(dhi, 329.575, delta=0.05)
        self.assertAlmostEqual(dni, 170.425, delta=0.05)

    def test_erbs_high_clearness_is_a_flat_fraction(self):
        dni, dhi = p.erbs_split(900.0, 1.0, 0.0, 1000.0)
        self.assertAlmostEqual(dhi, 0.165 * 900.0, delta=0.01)
        self.assertAlmostEqual(dni, 0.835 * 900.0, delta=0.01)

    def test_erbs_low_sun_has_no_direct_beam(self):
        dni, dhi = p.erbs_split(30.0, math.cos(math.radians(88.0)), 88.0, 1300.0)
        self.assertEqual(dni, 0.0)
        self.assertEqual(dhi, 30.0)


class PanelTests(unittest.TestCase):
    def test_flat_panel_sees_the_horizontal_irradiance(self):
        sun = p.SunPosition(math.cos(math.radians(30.0)), 30.0, 150.0, 11.0)
        poa, beam, sky, ground = p.poa_fixed_tilt(800.0, 700.0, 150.0, sun, 0.0)
        self.assertAlmostEqual(beam, 700.0 * math.cos(math.radians(30.0)), places=6)
        self.assertAlmostEqual(sky, 150.0, places=6)
        self.assertAlmostEqual(ground, 0.0, places=6)
        self.assertAlmostEqual(poa, beam + 150.0, places=6)

    def test_panel_facing_the_sun_gets_the_full_beam(self):
        # tilt 30 facing south, sun at zenith 30 due south: the angle of incidence is zero
        sun = p.SunPosition(math.cos(math.radians(30.0)), 30.0, 180.0, 12.0)
        poa, beam, sky, ground = p.poa_fixed_tilt(800.0, 700.0, 100.0, sun, 30.0)
        self.assertAlmostEqual(beam, 700.0, places=6)

    def test_vertical_panel_gets_half_the_sky_and_half_the_ground_term(self):
        sun = p.SunPosition(math.cos(math.radians(60.0)), 60.0, 90.0, 9.0)
        poa, beam, sky, ground = p.poa_fixed_tilt(500.0, 400.0, 100.0, sun, 90.0)
        self.assertAlmostEqual(sky, 50.0, places=6)
        self.assertAlmostEqual(ground, 500.0 * 0.25 / 2.0, places=6)

    def test_beam_never_goes_negative_when_the_sun_is_behind_the_panel(self):
        sun = p.SunPosition(math.cos(math.radians(60.0)), 60.0, 0.0, 6.0)  # sun in the north, panel faces south
        poa, beam, sky, ground = p.poa_fixed_tilt(500.0, 400.0, 100.0, sun, 60.0)
        self.assertEqual(beam, 0.0)

    def test_cell_temperature_rises_with_irradiance(self):
        self.assertAlmostEqual(p.ross_cell_temp_c(1000.0, 20.0), 20.0 + 0.0208 * 1000.0, places=6)
        self.assertEqual(p.ross_cell_temp_c(0.0, 17.0), 17.0)

    def test_dc_power_at_the_rating_conditions_is_the_nameplate(self):
        self.assertAlmostEqual(p.pvwatts_dc_w(1000.0, 25.0, 1.675e6, -0.0035), 1.675e6, places=3)
        self.assertAlmostEqual(p.pvwatts_dc_w(500.0, 25.0, 1.675e6, -0.0035), 0.5 * 1.675e6, places=3)

    def test_hot_cells_lose_power(self):
        # 20 degrees above the reference at -0.35 percent per degree is a 7 percent loss
        self.assertAlmostEqual(p.pvwatts_dc_w(1000.0, 45.0, 1.0e6, -0.0035), 0.93e6, places=3)


class InverterTests(unittest.TestCase):
    LIMIT = 1.25e6 / 0.96  # DC input limit for a 1.25 MWac inverter at eta_nom 0.96

    def test_no_dc_power_gives_no_ac_power(self):
        self.assertEqual(p.pvwatts_inverter_ac_w(0.0, self.LIMIT), 0.0)

    def test_efficiency_at_the_limit_equals_the_nominal_efficiency(self):
        ac = p.pvwatts_inverter_ac_w(self.LIMIT, self.LIMIT)
        self.assertAlmostEqual(ac, 0.96 * self.LIMIT, delta=1.0)

    def test_output_clips_at_the_ac_rating(self):
        rating = 0.96 * self.LIMIT
        self.assertAlmostEqual(p.pvwatts_inverter_ac_w(1.2 * self.LIMIT, self.LIMIT), rating, delta=1.0)
        self.assertAlmostEqual(p.pvwatts_inverter_ac_w(3.0 * self.LIMIT, self.LIMIT), rating, delta=1.0)
        self.assertAlmostEqual(rating, 1.25e6, delta=1.0)

    def test_half_load_efficiency(self):
        # zeta 0.5: 0.96/0.9637 x (-0.0081 - 0.0118 + 0.9858) = 0.96219
        ac = p.pvwatts_inverter_ac_w(0.5 * self.LIMIT, self.LIMIT)
        self.assertAlmostEqual(ac / (0.5 * self.LIMIT), 0.96219, delta=0.0005)

    def test_tiny_input_gives_zero_not_a_negative(self):
        self.assertEqual(p.pvwatts_inverter_ac_w(0.003 * self.LIMIT, self.LIMIT), 0.0)


class AmbientAndCloudTests(unittest.TestCase):
    def test_ambient_is_warmest_at_15_and_coolest_at_03(self):
        self.assertAlmostEqual(p.ambient_temp_c(15.0), 33.0, places=6)
        self.assertAlmostEqual(p.ambient_temp_c(3.0), 17.0, places=6)

    def test_clouds_repeat_for_the_same_seed_and_differ_for_another(self):
        a = [p.CloudModel(7).step(1.0) for _ in range(1)]  # a fresh model each time gives the same first value
        run = lambda seed: (lambda m: [m.step(1.0) for _ in range(5000)])(p.CloudModel(seed))
        self.assertEqual(run(7), run(7))
        self.assertNotEqual(run(7), run(8))
        self.assertEqual(a, [p.CloudModel(7).step(1.0)])

    def test_clouds_stay_in_range_and_are_mostly_clear(self):
        model = p.CloudModel(1)
        factors = [model.step(1.0) for _ in range(10800)]  # three hours at one second
        self.assertGreaterEqual(min(factors), 0.30 - 1e-9)  # deepest allowed cloud is 0.70
        self.assertLessEqual(max(factors), 1.0)
        self.assertLess(min(factors), 1.0)  # at least one cloud in three hours
        clear = sum(1 for f in factors if f == 1.0) / len(factors)
        self.assertGreater(clear, 0.5)


if __name__ == "__main__":
    unittest.main()
