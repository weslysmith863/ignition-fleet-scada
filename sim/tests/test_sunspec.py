"""Tests for sim.sunspec: encodings, the model chain, register positions, and the values served (ADR 0006 and 0009)."""
import random
import unittest
import urllib.error
from dataclasses import replace
from datetime import datetime, timezone

from sim import sunspec as s
from sim.model import PlantModel, SiteConfig
from sim.sunspec_layouts import LAYOUTS

NOON = datetime(2026, 6, 21, 18, 50, tzinfo=timezone.utc)
NIGHT = datetime(2026, 6, 21, 6, 0, tzinfo=timezone.utc)
CLEAR = SiteConfig(clouds_enabled=False)
EXPECTED_BODY_LENGTH = {1: 66, 103: 50, 123: 24, 203: 105, 302: 5, 303: 1, 307: 11, 713: 7, 802: 62}
BATTERY = replace(CLEAR, battery_w=2.5e6, battery_wh=10.0e6)  # Site 1's battery (ADR 0016): unit 7


def registers_at(when, limit_mw=None):
    model = PlantModel(CLEAR)
    if limit_mw is not None:
        model.set_limit(limit_mw, True)
    state = model.step(when, 1.0)
    return state, s.all_registers(state, CLEAR, random.Random(0), noise=False)


def value(regs, model_id, point):
    return regs[s.point_index(regs, model_id, point)]


def value32(regs, model_id, point):
    """A 32-bit point: the high word comes first."""
    index = s.point_index(regs, model_id, point)
    return (regs[index] << 16) | regs[index + 1]


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


class FaultInjectionTests(unittest.TestCase):
    """ADR 0017: a tripped inverter reports state 7 (Fault) and no power through its own unit, and nobody else is affected."""

    def registers(self, when, tripped):
        model = PlantModel(CLEAR)
        model.set_trip(tripped)
        state = model.step(when, 1.0)
        return s.all_registers(state, CLEAR, random.Random(0), noise=False)

    def test_the_tripped_inverter_reads_fault_and_zero_power_and_the_others_read_normally(self):
        regs = self.registers(NOON, 3)
        self.assertEqual(value(regs[3], 103, "St"), s.ST_FAULT)
        self.assertEqual(s.ST_FAULT, 7)
        self.assertEqual(signed(value(regs[3], 103, "W")), 0)
        self.assertEqual(signed(value(regs[3], 103, "DCW")), 0)
        for unit in (1, 2, 4):
            self.assertEqual(value(regs[unit], 103, "St"), s.ST_THROTTLED)  # clipping at noon, as before
            self.assertEqual(signed(value(regs[unit], 103, "W")), 12500)  # 1.25 MW in units of 100 W

    def test_the_trip_shows_even_when_the_inverter_would_be_asleep(self):
        regs = self.registers(NIGHT, 1)
        self.assertEqual(value(regs[1], 103, "St"), s.ST_FAULT)
        self.assertEqual(value(regs[2], 103, "St"), s.ST_SLEEPING)

    def test_with_nothing_tripped_no_inverter_reads_fault(self):
        regs = self.registers(NOON, 0)
        for unit in (1, 2, 3, 4):
            self.assertNotEqual(value(regs[unit], 103, "St"), s.ST_FAULT)


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


def text(regs, model_id, point):
    """A string point (such as the model name) decoded from its registers."""
    index = s.point_index(regs, model_id, point)
    size = next(entry[2] for entry in LAYOUTS[model_id] if entry[0] == point)
    data = b"".join(bytes([r >> 8, r & 0xFF]) for r in regs[index:index + size])
    return data.rstrip(b"\x00").decode("ascii")


class UnitIdTests(unittest.TestCase):
    """ADR 0014 decision 9: inverters are units 1 to N, then the weather station, then the meter."""

    def test_site_1_keeps_its_units(self):
        self.assertEqual(s.unit_ids(SiteConfig()), ((1, 2, 3, 4), 5, 6))

    def test_units_follow_the_inverter_count(self):
        self.assertEqual(s.unit_ids(replace(SiteConfig(), inverters=6)), ((1, 2, 3, 4, 5, 6), 7, 8))

    def test_a_six_inverter_plant_serves_eight_devices(self):
        config = replace(CLEAR, inverters=6)
        state = PlantModel(config).step(NOON, 1.0)
        regs = s.all_registers(state, config, random.Random(0), noise=False)
        self.assertEqual(sorted(regs), list(range(1, 9)))
        for unit in range(1, 7):
            self.assertIsNotNone(s.find_model(regs[unit], 103), unit)
            self.assertIsNotNone(s.find_model(regs[unit], 123), unit)
        for model_id in (302, 303, 307):
            self.assertIsNotNone(s.find_model(regs[7], model_id))
        self.assertIsNotNone(s.find_model(regs[8], 203))
        self.assertIsNone(s.find_model(regs[8], 103))

    def test_the_meter_of_a_six_inverter_plant_reads_its_rating_at_clear_noon(self):
        config = replace(CLEAR, inverters=6)
        state = PlantModel(config).step(NOON, 1.0)
        regs = s.all_registers(state, config, random.Random(0), noise=False)
        self.assertEqual(signed(value(regs[8], 203, "W")) * 1000, 7_500_000)  # six inverters of 1.25 MW, clipped

    def test_the_inverter_model_name_follows_the_rating(self):
        _, regs = registers_at(NOON)
        self.assertEqual(text(regs[1], 1, "Md"), "SIM-INV-1250")
        config = replace(CLEAR, inverter_ac_w=1.0e6)
        state = PlantModel(config).step(NOON, 1.0)
        other = s.all_registers(state, config, random.Random(0), noise=False)
        self.assertEqual(text(other[1], 1, "Md"), "SIM-INV-1000")


def battery_registers_at(when, mode=None, setpoint_mw=0.0, config=BATTERY, seconds=1.0):
    model = PlantModel(config)
    if mode is not None:
        model.set_battery(mode, setpoint_mw)
    state = model.step(when, seconds)
    return state, s.all_registers(state, config, random.Random(0), noise=False)


class BatteryRegisterTests(unittest.TestCase):
    """ADR 0016 decision 8: the battery is unit N+3, with the common block and SunSpec models 713 and 802, read-only."""

    def test_the_battery_is_unit_n_plus_3_and_only_when_there_is_one(self):
        self.assertEqual(s.battery_unit(BATTERY), 7)
        self.assertEqual(s.battery_unit(replace(BATTERY, inverters=6)), 9)
        self.assertIsNone(s.battery_unit(CLEAR))
        _, with_battery = battery_registers_at(NIGHT)
        _, without = registers_at(NIGHT)
        self.assertEqual(sorted(with_battery), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(sorted(without), [1, 2, 3, 4, 5, 6])

    def test_the_other_devices_are_unchanged_by_a_battery(self):
        _, with_battery = battery_registers_at(NOON)
        _, without = registers_at(NOON)
        for unit in range(1, 7):
            self.assertEqual(with_battery[unit], without[unit], unit)

    def test_the_chain_is_common_then_713_then_802(self):
        _, regs = battery_registers_at(NIGHT)
        bat = regs[7]
        self.assertEqual(bat[0:2], [0x5375, 0x6E53])
        self.assertEqual(s.find_model(bat, 1), 2)
        self.assertEqual(s.find_model(bat, 713), 70)
        self.assertEqual(s.find_model(bat, 802), 70 + 9)
        self.assertEqual(bat[-2:], [0xFFFF, 0])
        self.assertEqual(text(bat, 1, "Md"), "SIM-BATTERY-2500")
        self.assertEqual(value(bat, 1, "DA"), 7)

    def test_an_idle_battery_at_half_charge(self):
        _, regs = battery_registers_at(NIGHT)
        bat = regs[7]
        self.assertEqual((value(bat, 802, "WHRtg_SF"), value(bat, 802, "WHRtg")), (3, 10000))  # 10,000 kWh
        self.assertEqual(value(bat, 802, "WChaRteMax"), 2500)  # kW
        self.assertEqual(value(bat, 802, "WDisChaRteMax"), 2500)
        self.assertEqual(signed(value(bat, 802, "SoC_SF")), -2)
        self.assertEqual(value(bat, 802, "SoC"), 5000)
        self.assertEqual((value(bat, 802, "SoCMax"), value(bat, 802, "SoCMin")), (9000, 1000))
        self.assertEqual(signed(value(bat, 802, "W")), 0)
        self.assertEqual(value(bat, 802, "ChaSt"), s.CHA_HOLDING)
        self.assertEqual(value(bat, 802, "State"), s.BAT_STANDBY)
        self.assertEqual((value(bat, 802, "Typ"), value(bat, 802, "LocRemCtl")), (s.TYP_LITHIUM_ION, s.CTL_REMOTE))
        self.assertEqual(value(bat, 802, "SoH"), 10000)
        self.assertEqual(value(bat, 802, "DoD"), 5000)  # half of the 10 to 90 percent window is used
        self.assertEqual(value32(bat, 802, "NCyc"), 0)
        self.assertEqual(value(bat, 802, "V"), 0xFFFF)  # not implemented

    def test_model_713_agrees_with_model_802(self):
        _, regs = battery_registers_at(NIGHT)
        bat = regs[7]
        self.assertEqual(value(bat, 713, "WHRtg"), value(bat, 802, "WHRtg"))
        self.assertEqual(value(bat, 713, "SoC"), value(bat, 802, "SoC"))
        self.assertEqual(value(bat, 713, "WH_SF"), 3)
        self.assertEqual(signed(value(bat, 713, "Pct_SF")), -2)
        self.assertEqual(value(bat, 713, "WHAvail"), 4000)  # 5,000 kWh stored less the 1,000 kWh below the 10 percent limit
        self.assertEqual(value(bat, 713, "Sta"), 0xFFFF)

    def test_discharging_reads_as_positive_watts_connected_and_discharging(self):
        _, regs = battery_registers_at(NIGHT, "Discharge", 2.0)
        bat = regs[7]
        self.assertEqual(signed(value(bat, 802, "W")), 2000)
        self.assertEqual(value(bat, 802, "ChaSt"), s.CHA_DISCHARGING)
        self.assertEqual(value(bat, 802, "State"), s.BAT_CONNECTED)

    def test_charging_reads_as_negative_watts(self):
        _, regs = battery_registers_at(NIGHT, "Charge", 1.5)
        bat = regs[7]
        self.assertEqual(signed(value(bat, 802, "W")), -1500)
        self.assertEqual(value(bat, 802, "ChaSt"), s.CHA_CHARGING)
        self.assertEqual(value(bat, 802, "State"), s.BAT_CONNECTED)

    def test_asking_for_power_at_a_limit_reads_as_soc_protection(self):
        empty = replace(BATTERY, battery_soc_start=0.10)
        _, regs = battery_registers_at(NIGHT, "Discharge", 2.0, empty)
        self.assertEqual(signed(value(regs[7], 802, "W")), 0)
        self.assertEqual((value(regs[7], 802, "ChaSt"), value(regs[7], 802, "State")), (s.CHA_EMPTY, s.BAT_SOC_PROTECTION))
        full = replace(BATTERY, battery_soc_start=0.90)
        _, regs = battery_registers_at(NIGHT, "Charge", 2.0, full)
        self.assertEqual((value(regs[7], 802, "ChaSt"), value(regs[7], 802, "State")), (s.CHA_FULL, s.BAT_SOC_PROTECTION))

    def test_an_empty_battery_that_is_not_asked_for_power_is_standby(self):
        empty = replace(BATTERY, battery_soc_start=0.10)
        _, regs = battery_registers_at(NIGHT, None, 0.0, empty)
        self.assertEqual((value(regs[7], 802, "ChaSt"), value(regs[7], 802, "State")), (s.CHA_EMPTY, s.BAT_STANDBY))

    def test_a_discharge_blocked_only_by_the_export_cap_is_standby_not_protection(self):
        _, regs = battery_registers_at(NOON, "Discharge", 2.5)  # full sun: no room under the plant rating
        self.assertEqual(signed(value(regs[7], 802, "W")), 0)
        self.assertEqual((value(regs[7], 802, "ChaSt"), value(regs[7], 802, "State")), (s.CHA_HOLDING, s.BAT_STANDBY))

    def test_the_meter_reads_pv_plus_battery_and_counts_imported_energy(self):
        _, regs = battery_registers_at(NIGHT, "Discharge", 2.0)
        self.assertEqual(signed(value(regs[6], 203, "W")), 2000)  # kW
        _, regs = battery_registers_at(NIGHT, "Charge", 1.0, seconds=3600.0)
        self.assertEqual(signed(value(regs[6], 203, "W")), -1000)
        self.assertEqual(value32(regs[6], 203, "TotWhImp"), 1000)  # kWh, in the meter's SF 3 units
        self.assertEqual(value32(regs[6], 203, "TotWhExp"), 0)


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
