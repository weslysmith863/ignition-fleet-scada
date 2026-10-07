"""Tests for sim.opcua_server with a real OPC UA client. Skipped when asyncua is not installed (sim/requirements.txt)."""
import asyncio
import socket
import unittest
from datetime import datetime, timezone

from sim.model import SiteConfig
from sim.modbus_server import Simulation
from sim.plant_controller import PlantController

try:
    from asyncua import Client
    from sim import opcua_server
except ImportError:  # the standard-library-only test run
    opcua_server = None

NOON_JUNE = datetime(2026, 6, 21, 18, 50, tzinfo=timezone.utc)  # clear sky, the plant clips at 5 MW


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def until(condition, timeout_s=5.0):
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out waiting for the condition")
        await asyncio.sleep(0.05)


@unittest.skipIf(opcua_server is None, "asyncua is not installed")
class OpcUaServerTests(unittest.IsolatedAsyncioTestCase):
    CONFIG = SiteConfig(clouds_enabled=False)

    async def asyncSetUp(self):
        self.simulation = Simulation(self.CONFIG, noise=False)
        self.simulation.tick(NOON_JUNE, 1.0)
        self.controller = PlantController(self.simulation)
        started = asyncio.Event()
        self.url = opcua_server.endpoint_url("127.0.0.1", free_port())
        port = int(self.url.rsplit(":", 1)[1].split("/")[0])
        self.task = asyncio.create_task(opcua_server.serve(self.controller, "127.0.0.1", port, log=lambda message: None, started=started))
        await asyncio.wait_for(started.wait(), 10)

    async def asyncTearDown(self):
        self.task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await self.task

    async def node(self, client, name):
        namespace = await client.get_namespace_index(opcua_server.NAMESPACE_URI)
        return client.get_node("ns=%d;s=%s.%s" % (namespace, opcua_server.OBJECT_NAME, name))

    async def test_a_client_reads_all_six_nodes_with_their_types(self):
        async with Client(self.url) as client:
            values = {name: await (await self.node(client, name)).read_value() for name in opcua_server.VARIANT_TYPES}
        self.assertEqual(len(values), 6)
        self.assertEqual(values["RatedMW"], 5.0)
        self.assertEqual(values["ActivePowerLimit_MW"], 5.0)
        self.assertIs(values["LimitEnable"], False)
        self.assertIs(values["LimitActive"], False)
        self.assertAlmostEqual(values["POI_MW"], 5.0, places=3)
        self.assertEqual(values["Status"], "Producing")

    async def test_a_written_limit_curtails_the_plant_and_a_clamped_value_is_written_back(self):
        async with Client(self.url) as client:
            limit, enable = await self.node(client, "ActivePowerLimit_MW"), await self.node(client, "LimitEnable")
            await limit.write_value(3.0)
            await enable.write_value(True)
            await until(lambda: self.controller.enabled and self.controller.limit_mw == 3.0)
            self.simulation.tick(NOON_JUNE, 1.0)  # the plant model applies the limit on its next step
            poi, active, status = [await self.node(client, n) for n in ("POI_MW", "LimitActive", "Status")]
            for _ in range(40):
                if await active.read_value():
                    break
                await asyncio.sleep(0.1)
            self.assertTrue(await active.read_value())
            self.assertAlmostEqual(await poi.read_value(), 3.0, places=3)
            self.assertEqual(await status.read_value(), "Curtailed")

            await limit.write_value(99.0)  # above the rating: accepted as 5.0 and shown as 5.0
            await until(lambda: self.controller.limit_mw == 5.0)
            for _ in range(40):
                if await limit.read_value() == 5.0:
                    break
                await asyncio.sleep(0.1)
            self.assertEqual(await limit.read_value(), 5.0)

    async def test_the_read_only_nodes_refuse_a_client_write(self):
        async with Client(self.url) as client:
            poi = await self.node(client, "POI_MW")
            rated = await self.node(client, "RatedMW")
            with self.assertRaises(Exception):
                await poi.write_value(1.0)
            with self.assertRaises(Exception):
                await rated.write_value(1.0)

    async def test_a_plant_without_a_battery_has_no_battery_nodes(self):
        if self.CONFIG.has_battery:
            self.skipTest("this plant has a battery")
        async with Client(self.url) as client:
            with self.assertRaises(Exception):
                await (await self.node(client, "BatteryMode")).read_value()


BATTERY_CONFIG = SiteConfig(clouds_enabled=False, battery_w=2.5e6, battery_wh=10.0e6)


@unittest.skipIf(opcua_server is None, "asyncua is not installed")
class OpcUaBatteryTests(OpcUaServerTests):
    """The same plant with a battery (ADR 0016): everything above still holds while the battery is idle, plus two nodes."""
    CONFIG = BATTERY_CONFIG

    async def test_the_battery_nodes_start_idle_and_zero(self):
        async with Client(self.url) as client:
            mode = await (await self.node(client, "BatteryMode")).read_value()
            setpoint = await (await self.node(client, "BatterySetpoint_MW")).read_value()
        self.assertEqual((mode, setpoint), ("Idle", 0.0))

    async def test_a_written_battery_command_reaches_the_model_and_a_clamped_value_is_written_back(self):
        async with Client(self.url) as client:
            mode, setpoint = await self.node(client, "BatteryMode"), await self.node(client, "BatterySetpoint_MW")
            await mode.write_value("Discharge")
            await setpoint.write_value(99.0)  # above the battery rating: accepted as 2.5
            await until(lambda: self.simulation.model.battery_mode == "Discharge" and self.simulation.model.battery_setpoint_w == 2.5e6)
            for _ in range(40):
                if await setpoint.read_value() == 2.5:
                    break
                await asyncio.sleep(0.1)
            self.assertEqual(await setpoint.read_value(), 2.5)
            await mode.write_value("Nonsense")  # not a mode: ignored, and the accepted one is shown again
            for _ in range(40):
                if await mode.read_value() == "Discharge":
                    break
                await asyncio.sleep(0.1)
            self.assertEqual(await mode.read_value(), "Discharge")
            self.assertEqual(self.simulation.model.battery_mode, "Discharge")


if __name__ == "__main__":
    unittest.main()
