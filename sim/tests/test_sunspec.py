"""Tests for sim.sunspec: encodings, the model chain, register positions, and the values served (ADR 0006 and 0009)."""
import random
import unittest
import urllib.error
from datetime import datetime, timezone

from sim import sunspec as s
from sim.model import PlantModel, SiteConfig
from sim.sunspec_layouts import LAYOUTS

NOON = datetime(2026, 6, 21, 18, 50, tzinfo=timezone.utc)
NIGHT = datetime(2026, 6, 21, 6, 0, tzinfo=timezone.utc)
CLEAR = SiteConfig(clouds_enabled=False)
EXPECTED_BODY_LENGTH = {1: 66, 103: 50, 123: 24, 203: 105, 302: 5, 303: 1, 307: 11}


def registers_at(when, limit_mw=None):
    model = PlantModel(CLEAR)
    if limit_mw is not None:
        model.set_limit(limit_mw, True)
    state = model.step(when, 1.0)
    return state, s.all_registers(state, CLEAR, random.Random(0), noise=False)


def value(regs, model_id, point):
    return regs[s.point_index(regs, model_id, point)]


def signed(v):
    return v - 0x10000 if v >= 0x8000 else v


class EncodingTests(unittest.TestCase):
    def test_raw_divides_by_ten_to_the_scale_factor(self):
        self.assertEqual(s.raw(1.25e6, 2), 12500)
        self.assertEqual(s.raw(60.0, -2), 6000)
        self.assertEqual(s.raw(123.4, -1), 1234)

    def test_negative_numbers_are_twos_complement(self):
        self.assertEqual(s._encode("int16", 1, -1), [0xFFFF])
        self.assertEqual(s._encode("sunssf", 1, -2), [0xFFFE])

    def test_values_outside_the_register_range_are_clamped(self):
        self.assertEqual(s._encode("int16", 1, 99999), [32767])
        self.assertEqual(s._encode("uint16", 1, -5), [0])

    def test_32_bit_values_put_the_high_word_first(self):
        self.assertEqual(s._encode("acc32", 2, 0x00012345), [0x0001, 0x2345])

    def test_accumulators_roll_over(self):
        self.assertEqual(s._encode("acc32", 2, 0x100000005), [0, 5])

    def test_strings_pack_two_characters_per_register(self):
        self.assertEqual(s._encode("string", 2, "AB"), [0x4142, 0])
        self.assertEqual(len(s._encode("string", 16, "x")), 16)


class ModelChainTests(unittest.TestCase):
    def test_every_block_length_matches_the_model(self):
        for model_id, expected in EXPECTED_BODY_LENGTH.items():
            block = s.model_block(model_id)
            self.assertEqual(block[1], expected, model_id)
            self.assertEqual(len(block), expected + 2, model_id)

    def test_unknown_point_names_are_rejected(self):
        with self.assertRaises(KeyError):
            s.model_block(103, {"NotAPoint": 1})

    def test_inverter_chain_matches_the_spike_layout(self):
        _, regs = registers_at(NOON)
        inv = regs[1]
        self.assertEqual(inv[0:2], [0x5375, 0x6E53])  # 'SunS' at address 40000
        self.assertEqual(s.find_model(inv, 1), 2)
        self.assertEqual(s.find_model(inv, 103), 70)  # address 40070, as in the Phase 1 spike
        self.assertEqual(inv[70:72], [103, 50])
        self.assertEqual(s.find_model(inv, 123), 70 + 52)
        self.assertEqual(inv[-2:], [0xFFFF, 0])  # end model
        self.assertIsNone(s.find_model(inv, 999))

    def test_spike_positions_for_w_and_hz(self):
        _, regs = registers_at(NOON)
        base = s.BASE_ADDRESS
        inv = regs[1]
        self.assertEqual(base + s.point_index(inv, 103, "W"), 40084)
        self.assertEqual(base + s.point_index(inv, 103, "W_SF"), 40085)
        self.assertEqual(base + s.point_index(inv, 103, "Hz"), 40086)
        self.assertEqual(base + s.point_index(inv, 103, "Hz_SF"), 40087)

    def test_each_device_has_the_expected_models(self):
        _, regs = registers_at(NOON)
        self.assertEqual(sorted(regs), [1, 2, 3, 4, 5, 6])
        for unit in (1, 2, 3, 4):
            self.assertIsNotNone(s.find_model(regs[unit], 103))
            self.assertIsNotNone(s.find_model(regs[unit], 123))
        for model_id in (302, 303, 307):
            self.assertIsNotNone(s.find_model(regs[5], model_id))
        self.assertIsNotNone(s.find_model(regs[6], 203))
        self.assertIsNone(s.find_model(regs[6], 103))

    def test_layouts_match_the_public_sunspec_files(self):  # skips itself when offline
        from sim.tools import gen_sunspec_layouts
        try:
            fetched = gen_sunspec_layouts.fetch_layouts()
        except (urllib.error.URLError, OSError) as error:
            self.skipTest("offline: %s" % error)
        self.assertEqual(fetched, {k: [tuple(p) for p in v] for k, v in LAYOUTS.items()})


class ServedValueTests(unittest.TestCase):
    def test_clear_noon_inverter_values(self):
        state, regs = registers_at(NOON)
        inv = regs[1]
        self.assertEqual(value(inv, 103, "W_SF"), 2)
        self.assertEqual(signed(value(inv, 103, "W")) * 100, 1_250_000)  # clipped at the rating
        self.assertEqual(value(inv, 103, "Hz"), 6000)
        self.assertEqual(signed(value(inv, 103, "Hz_SF")), -2)
        self.assertEqual(value(inv, 103, "PhVphA"), 3464)  # 600 V line to line is 346.4 V to neutral
        self.assertEqual(value(inv, 103, "PPVphAB"), 6000)
        self.assertEqual(value(inv, 103, "A"), 36084)  # three phases of 1203.0 A, in 0.1 A steps
        self.assertEqual(value(inv, 103, "St"), s.ST_THROTTLED)  # clipping counts as throttled
        self.assertEqual(value(inv, 123, "WMaxLim_Ena"), 0)
        self.assertEqual(value(inv, 123, "WMaxLimPct"), 10000)
        self.assertEqual(signed(value(inv, 123, "WMaxLimPct_SF")), -2)

    def test_dc_power_is_above_the_ac_power_when_clipping(self):
        _, regs = registers_at(NOON)
        self.assertGreater(signed(value(regs[1], 103, "DCW")), signed(value(regs[1], 103, "W")))

    def test_a_limit_shows_up_as_a_throttled_state_and_a_percentage(self):
        _, regs = registers_at(NOON, limit_mw=3.0)
        inv = regs[1]
        self.assertEqual(signed(value(inv, 103, "W")) * 100, 750_000)
        self.assertEqual(value(inv, 103, "St"), s.ST_THROTTLED)
        self.assertEqual(value(inv, 123, "WMaxLim_Ena"), 1)
        self.assertEqual(value(inv, 123, "WMaxLimPct"), 6000)  # 3 MW of a 5 MW plant is 60.00 percent
        self.assertEqual(signed(value(regs[6], 203, "W")), 3000)  # meter in kW

    def test_night_inverters_sleep_and_make_nothing(self):
        _, regs = registers_at(NIGHT)
        self.assertEqual(value(regs[1], 103, "St"), s.ST_SLEEPING)
        self.assertEqual(signed(value(regs[1], 103, "W")), 0)
        self.assertEqual(value(regs[5], 302, "POAI"), 0)

    def test_weather_station_values(self):
        state, regs = registers_at(NOON)
        wx = regs[5]
        self.assertEqual(value(wx, 302, "GHI"), round(state["ghi_w_m2"]))
        self.assertEqual(value(wx, 302, "POAI"), round(state["poa_w_m2"]))
        self.assertEqual(value(wx, 302, "DNI"), round(state["dni_w_m2"]))
        self.assertEqual(value(wx, 302, "OTI"), 0xFFFF)  # not implemented
        self.assertEqual(signed(value(wx, 303, "TmpBOM")), round(state["module_c"] * 10))
        self.assertEqual(signed(value(wx, 307, "TmpAmb")), round(state["ambient_c"] * 10))
        self.assertEqual(value(wx, 307, "WndSpd"), 0x8000)  # wind is not modeled

    def test_meter_values(self):
        state, regs = registers_at(NOON)
        meter = regs[6]
        self.assertEqual(value(meter, 203, "W_SF"), 3)
        self.assertEqual(signed(value(meter, 203, "W")), 5000)  # 5 MW in kW
        self.assertEqual(value(meter, 203, "PPV"), 3450)  # 34.5 kV in 10 V steps
        self.assertEqual(value(meter, 203, "TotWhImp"), 0)
        index = s.point_index(meter, 203, "TotWhExp")
        exported_kwh = (meter[index] << 16) | meter[index + 1]
        self.assertEqual(exported_kwh, int(state["energy_wh"] / 1000.0))

    def test_inverter_energy_counter_counts_up_in_watt_hours(self):
        model = PlantModel(CLEAR)
        state = model.step(NOON, 3600.0)  # an hour at the noon rate
        regs = s.all_registers(state, CLEAR, random.Random(0), noise=False)
        index = s.point_index(regs[1], 103, "WH")
        self.assertAlmostEqual((regs[1][index] << 16) | regs[1][index + 1], 1_250_000, delta=2)

    def test_unimplemented_inverter_points_use_the_sunspec_markers(self):
        _, regs = registers_at(NOON)
        self.assertEqual(value(regs[1], 103, "DCA"), 0xFFFF)
        self.assertEqual(value(regs[1], 103, "TmpSnk"), 0x8000)

    def test_noise_is_repeatable_for_a_seed(self):
        state = PlantModel(CLEAR).step(NOON, 1.0)
        a = s.all_registers(state, CLEAR, random.Random(5))
        b = s.all_registers(state, CLEAR, random.Random(5))
        c = s.all_registers(state, CLEAR, random.Random(6))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


if __name__ == "__main__":
    unittest.main()
