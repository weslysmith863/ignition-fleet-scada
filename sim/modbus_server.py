"""Modbus TCP server for the Phase 1 simulator (ADR 0006, ADR 0009). The Modbus part is standard library only.

Serves read-only SunSpec registers for every device of one plant on one endpoint: N inverters on units 1 to N, the weather
station on unit N+1, and the POI meter on unit N+2 (ADR 0014 decision 9; Site 1 has N = 4, so units 1 to 6). The plant's shape
comes from --inverters, --inverter-kw, and --seed, or from SIM_INVERTERS, SIM_INVERTER_KW, and SIM_SEED (ADR 0014 decision 3);
with none of them it is Site 1. A simulation thread steps the plant model once a second and swaps in fresh registers.

The same process also serves the OPC UA plant controller (sim/opcua_server.py, ADR 0010) on --opcua-port when asyncua is
installed (sim/requirements.txt); without it the Modbus server runs alone and says so.

    python -m sim.modbus_server --port 15020 --start 2026-06-21T18:00:00Z --seed 1

Answers function 3 (read holding registers) only. Reads outside a device's SunSpec block get "illegal data address", writes
and other functions get "illegal function", and an unknown unit ID gets "gateway target failed" (0x0B).
"""
import argparse
import asyncio
import os
import random
import socketserver
import struct
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sim import sunspec
from sim.model import PlantModel, SiteConfig

MAX_READ_REGISTERS = 125
MAX_INVERTERS = 245  # the meter is unit N+2, and Modbus unit IDs stop at 247
MAX_INVERTER_KW = 2000  # W_SF is fixed at 2, so a signed 16-bit register tops out at 3.27 MW, and DC power runs near 1.34 times AC


def log(message):
    print(time.strftime("%H:%M:%S"), message, flush=True)


class Simulation:
    """The plant model plus the register images built from it. Handlers read `registers`, which is swapped whole."""

    def __init__(self, config=SiteConfig(), noise=True):
        self.config = config
        self.model = PlantModel(config)
        self._rng = random.Random(config.seed + 1000)  # a separate stream from the clouds
        self._noise = noise
        self.registers = {}
        self.state = None

    def tick(self, now_utc, dt_s):
        self.state = self.model.step(now_utc, dt_s)
        self.registers = sunspec.all_registers(self.state, self.config, self._rng, self._noise)

    def run_forever(self, start_utc, tick_s=1.0):
        """Advance in real time from start_utc, one tick per tick_s of wall clock."""
        wall_start = time.monotonic()
        next_tick = wall_start
        while True:
            now = start_utc + timedelta(seconds=time.monotonic() - wall_start)
            self.tick(now, tick_s)
            next_tick += tick_s
            time.sleep(max(0.0, next_tick - time.monotonic()))


class Handler(socketserver.BaseRequestHandler):
    def _read_exact(self, count):
        data = b""
        while len(data) < count:
            chunk = self.request.recv(count - len(data))
            if not chunk:
                return None
            data += chunk
        return data

    def handle(self):
        if self.server.verbose:
            log("connection from %s:%d" % self.client_address)
        while True:
            head = self._read_exact(7)  # MBAP header: transaction, protocol, length, unit
            if head is None:
                return
            tid, proto, length, unit = struct.unpack(">HHHB", head)
            pdu = self._read_exact(length - 1)
            if pdu is None:
                return
            response = self._respond(unit, pdu)
            self.request.sendall(struct.pack(">HHHB", tid, proto, len(response) + 1, unit) + response)

    def _respond(self, unit, pdu):
        function = pdu[0]
        if function != 3 or len(pdu) < 5:
            return bytes([function | 0x80, 0x01])  # illegal function
        start, count = struct.unpack(">HH", pdu[1:5])
        registers = self.server.registers_for(unit)
        if self.server.verbose:
            log("unit %d  FC3  start=%d count=%d" % (unit, start, count))
        if registers is None:
            return bytes([0x83, 0x0B])  # gateway target device failed to respond
        if count < 1 or count > MAX_READ_REGISTERS:
            return bytes([0x83, 0x03])  # illegal data value
        first = start - sunspec.BASE_ADDRESS
        if first < 0 or first + count > len(registers):
            return bytes([0x83, 0x02])  # illegal data address
        values = registers[first:first + count]
        return bytes([3, count * 2]) + b"".join(struct.pack(">H", v) for v in values)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, registers_for, verbose=False):
        super().__init__(address, Handler)
        self.registers_for = registers_for  # unit id -> register list, or None
        self.verbose = verbose


def resolve_start(argument, environment_value):
    """The simulated start time (UTC): the --start argument, else the SIM_START setting, else the real clock now.
    An empty value counts as not set, so an unset Compose variable means real time."""
    text = (argument or environment_value or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _setting(argument, environment_value, convert):
    """The command-line value, else the environment value converted, else None. An empty or blank setting counts as not set."""
    if argument is not None:
        return argument
    text = (environment_value or "").strip()
    return convert(text) if text else None


def plant_config(args, environ):
    """The plant's shape (ADR 0014 decision 3): each of inverters, inverter_kw, and seed comes from its command-line argument,
    else its SIM_ setting, else the Site 1 default. A value the register map cannot hold is an error, never a silent clamp."""
    changes = {}
    inverters = _setting(args.inverters, environ.get("SIM_INVERTERS"), int)
    if inverters is not None:
        if not 1 <= inverters <= MAX_INVERTERS:
            raise ValueError("inverters must be 1 to %d, not %d" % (MAX_INVERTERS, inverters))
        changes["inverters"] = inverters
    inverter_kw = _setting(args.inverter_kw, environ.get("SIM_INVERTER_KW"), float)
    if inverter_kw is not None:
        if not 0 < inverter_kw <= MAX_INVERTER_KW:
            raise ValueError("inverter kW must be above 0 and at most %d, not %g" % (MAX_INVERTER_KW, inverter_kw))
        changes["inverter_ac_w"] = inverter_kw * 1000.0
    seed = _setting(args.seed, environ.get("SIM_SEED"), int)
    if seed is not None:
        changes["seed"] = seed
    return replace(SiteConfig(), clouds_enabled=not args.no_clouds, **changes)


def start_opcua(simulation, host, port):
    """Serve the plant controller over OPC UA in its own thread, if asyncua is installed. Returns True when started."""
    try:
        from sim import opcua_server
    except ImportError:
        log("OPC UA plant controller is OFF: asyncua is not installed (pip install -r sim/requirements.txt)")
        return False
    from sim.plant_controller import PlantController
    controller = PlantController(simulation)

    def run():
        try:
            asyncio.run(opcua_server.serve(controller, host, port, log=log))
        except Exception as error:  # for example the port is already in use
            log("OPC UA plant controller stopped: %r" % (error,))

    threading.Thread(target=run, daemon=True).start()
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15020)
    parser.add_argument("--opcua-port", type=int, default=14840, help="OPC UA plant controller port; 0 turns it off")
    parser.add_argument("--start", default=None, help="simulated start time, UTC, e.g. 2026-06-21T18:00:00Z (default: the SIM_START setting, else now)")
    parser.add_argument("--inverters", type=int, default=None, help="number of inverters (default: the SIM_INVERTERS setting, else 4)")
    parser.add_argument("--inverter-kw", type=float, default=None, help="AC rating of each inverter in kW (default: the SIM_INVERTER_KW setting, else 1250)")
    parser.add_argument("--seed", type=int, default=None, help="cloud seed (default: the SIM_SEED setting, else 1)")
    parser.add_argument("--no-clouds", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="log every connection and read")
    args = parser.parse_args(argv)

    start = resolve_start(args.start, os.environ.get("SIM_START"))
    try:
        config = plant_config(args, os.environ)
    except ValueError as error:
        parser.error(str(error))
    simulation = Simulation(config)
    simulation.tick(start, 0.0)  # registers exist before the first client connects
    threading.Thread(target=simulation.run_forever, args=(start,), daemon=True).start()
    if args.opcua_port:
        start_opcua(simulation, args.host, args.opcua_port)
    server = Server((args.host, args.port), lambda unit: simulation.registers.get(unit), args.verbose)
    log("simulator serving units %s on %s:%d (%d inverters of %g kW), simulated start %s, seed %d"
        % (sorted(simulation.registers), args.host, args.port, config.inverters, config.inverter_ac_w / 1000.0,
           start.strftime("%Y-%m-%d %H:%M:%SZ"), config.seed))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("stopping")
        return 0


if __name__ == "__main__":
    sys.exit(main())
