"""Tests for sim.modbus_server: reads over a real socket, plus the error answers (ADR 0006 and 0009)."""
import socket
import struct
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sim import sunspec
from sim.model import SiteConfig
from sim.modbus_server import Server, Simulation, plant_config, resolve_start

NOON = datetime(2026, 6, 21, 18, 50, tzinfo=timezone.utc)
CLEAR = SiteConfig(clouds_enabled=False)


def request(port, unit, function, payload):
    with socket.create_connection(("127.0.0.1", port), timeout=3) as conn:
        conn.sendall(struct.pack(">HHHBB", 1, 0, 2 + len(payload), unit, function) + payload)
        head = _recv(conn, 7)
        _, _, length, answered_unit = struct.unpack(">HHHB", head)
        assert answered_unit == unit
        return _recv(conn, length - 1)


def _recv(conn, count):
    data = b""
    while len(data) < count:
        chunk = conn.recv(count - len(data))
        assert chunk, "connection closed early"
        data += chunk
    return data


def read_registers(port, unit, start, count):
    pdu = request(port, unit, 3, struct.pack(">HH", start, count))
    if pdu[0] & 0x80:
        return ("exception", pdu[0], pdu[1])
    return list(struct.unpack(">%dH" % (pdu[1] // 2), pdu[2:]))


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = Simulation(CLEAR, noise=False)
        cls.sim.tick(NOON, 1.0)
        cls.server = Server(("127.0.0.1", 0), lambda unit: cls.sim.registers.get(unit))
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_the_sunspec_marker_and_model_header_are_where_a_client_looks(self):
        self.assertEqual(read_registers(self.port, 1, 40000, 2), [0x5375, 0x6E53])
        self.assertEqual(read_registers(self.port, 1, 40070, 2), [103, 50])

    def test_power_and_its_scale_factor_read_together(self):
        w, w_sf, hz, hz_sf = read_registers(self.port, 1, 40084, 4)
        self.assertEqual((w, w_sf), (12500, 2))  # 12500 x 100 W = 1.25 MW, clipped at the rating
        self.assertEqual((hz, hz_sf), (6000, 0xFFFE))  # 60.00 Hz with a scale factor of -2

    def test_each_unit_answers_for_itself(self):
        inverter = read_registers(self.port, 3, 40070, 2)
        meter_chain = sunspec.find_model(self.sim.registers[6], 203)
        self.assertEqual(inverter, [103, 50])
        self.assertEqual(read_registers(self.port, 6, 40000 + meter_chain, 2), [203, 105])
        self.assertEqual(read_registers(self.port, 5, 40000 + sunspec.find_model(self.sim.registers[5], 302), 2), [302, 5])

    def test_a_full_size_read_works(self):
        values = read_registers(self.port, 1, 40000, 125)
        self.assertEqual(len(values), 125)

    def test_unknown_unit_gets_gateway_target_failed(self):
        self.assertEqual(read_registers(self.port, 9, 40084, 1), ("exception", 0x83, 0x0B))

    def test_addresses_outside_the_block_get_illegal_data_address(self):
        self.assertEqual(read_registers(self.port, 1, 100, 1), ("exception", 0x83, 0x02))
        end = sunspec.BASE_ADDRESS + len(self.sim.registers[1])
        self.assertEqual(read_registers(self.port, 1, end - 1, 2), ("exception", 0x83, 0x02))
        self.assertEqual(len(read_registers(self.port, 1, end - 2, 2)), 2)  # the end model is readable

    def test_oversized_reads_get_illegal_data_value(self):
        self.assertEqual(read_registers(self.port, 1, 40000, 126), ("exception", 0x83, 0x03))
        self.assertEqual(read_registers(self.port, 1, 40000, 0), ("exception", 0x83, 0x03))

    def test_writes_and_other_functions_get_illegal_function(self):
        write_single = request(self.port, 1, 6, struct.pack(">HH", 40084, 1))
        self.assertEqual(list(write_single), [0x86, 0x01])
        read_input = request(self.port, 1, 4, struct.pack(">HH", 40084, 1))
        self.assertEqual(list(read_input), [0x84, 0x01])

    def test_registers_follow_the_simulation_when_it_ticks(self):
        before = self.sim.registers[6]
        self.sim.tick(NOON.replace(hour=14), 1.0)  # earlier in the day, lower power
        try:
            after = read_registers(self.port, 6, 40000 + sunspec.point_index(self.sim.registers[6], 203, "W"), 1)
            self.assertNotEqual(after, [before[sunspec.point_index(before, 203, "W")]])
        finally:
            self.sim.tick(NOON, 1.0)


class SimulationTests(unittest.TestCase):
    def test_two_runs_with_the_same_seed_serve_the_same_registers(self):
        def run(seed):
            sim = Simulation(SiteConfig(seed=seed))
            for second in range(120):
                sim.tick(NOON + timedelta(seconds=second), 1.0)
            return sim.registers
        self.assertEqual(run(2), run(2))


def arguments(**given):
    values = {"inverters": None, "inverter_kw": None, "seed": None, "no_clouds": False}
    values.update(given)
    return SimpleNamespace(**values)


class PlantConfigTests(unittest.TestCase):
    """ADR 0014 decision 3: the plant's shape comes from settings, so a second container can be a different plant."""
    SETTINGS = {"SIM_INVERTERS": "6", "SIM_INVERTER_KW": "1250", "SIM_SEED": "7"}

    def test_nothing_given_means_site_1(self):
        self.assertEqual(plant_config(arguments(), {}), SiteConfig())

    def test_settings_shape_the_plant(self):
        config = plant_config(arguments(), self.SETTINGS)
        self.assertEqual((config.inverters, config.inverter_ac_w, config.seed), (6, 1.25e6, 7))

    def test_arguments_win_over_settings(self):
        config = plant_config(arguments(inverters=2, inverter_kw=800.0, seed=3), self.SETTINGS)
        self.assertEqual((config.inverters, config.inverter_ac_w, config.seed), (2, 8.0e5, 3))

    def test_empty_settings_count_as_not_set(self):
        self.assertEqual(plant_config(arguments(), {"SIM_INVERTERS": "", "SIM_INVERTER_KW": "  ", "SIM_SEED": ""}), SiteConfig())

    def test_the_no_clouds_flag_turns_clouds_off(self):
        self.assertFalse(plant_config(arguments(no_clouds=True), {}).clouds_enabled)

    def test_values_the_register_map_cannot_hold_are_errors_not_silent_clamps(self):
        for given in ({"SIM_INVERTERS": "0"}, {"SIM_INVERTERS": "246"}, {"SIM_INVERTERS": "many"},
                      {"SIM_INVERTER_KW": "0"}, {"SIM_INVERTER_KW": "2001"}, {"SIM_SEED": "x"}):
            with self.assertRaises(ValueError, msg=str(given)):
                plant_config(arguments(), given)

    def test_a_six_inverter_simulation_serves_inverters_weather_and_meter(self):
        sim = Simulation(replace(CLEAR, inverters=6))
        sim.tick(NOON, 1.0)
        self.assertEqual(sorted(sim.registers), list(range(1, 9)))


class StartTimeTests(unittest.TestCase):
    def test_the_argument_wins_over_the_setting(self):
        self.assertEqual(resolve_start("2026-10-05T17:00:00Z", "2026-01-01T00:00:00Z"), datetime(2026, 10, 5, 17, 0, tzinfo=timezone.utc))

    def test_the_setting_is_used_when_there_is_no_argument(self):
        self.assertEqual(resolve_start(None, "2026-10-05T17:00:00Z"), datetime(2026, 10, 5, 17, 0, tzinfo=timezone.utc))

    def test_neither_or_an_empty_setting_means_the_real_clock(self):
        for empty in (None, "", "   "):
            before = datetime.now(timezone.utc)
            got = resolve_start(None, empty)
            self.assertTrue(before <= got <= datetime.now(timezone.utc))

    def test_a_badly_formed_time_is_an_error_not_a_silent_default(self):
        with self.assertRaises(ValueError):
            resolve_start("tomorrow noon", None)


if __name__ == "__main__":
    unittest.main()
