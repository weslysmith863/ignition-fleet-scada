"""Modbus TCP server for the Phase 1 simulator (ADR 0006, ADR 0009). The Modbus part is standard library only.

Serves read-only SunSpec registers for six devices on one endpoint: inverters on units 1 to 4, the weather station on
unit 5, and the POI meter on unit 6. A simulation thread steps the plant model once a second and swaps in fresh registers.

The same process also serves the OPC UA plant controller (sim/opcua_server.py, ADR 0010) on --opcua-port when asyncua is
installed (sim/requirements.txt); without it the Modbus server runs alone and says so.

    python -m sim.modbus_server --port 15020 --start 2026-06-21T18:00:00Z --seed 1

Answers function 3 (read holding registers) only. Reads outside a device's SunSpec block get "illegal data address", writes
and other functions get "illegal function", and an unknown unit ID gets "gateway target failed" (0x0B).
"""
import argparse
import asyncio
import random
import socketserver
import struct
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from sim import sunspec
from sim.model import PlantModel, SiteConfig

MAX_READ_REGISTERS = 125


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
    parser.add_argument("--start", default=None, help="simulated start time, UTC, e.g. 2026-06-21T18:00:00Z (default: now)")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--no-clouds", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="log every connection and read")
    args = parser.parse_args(argv)

    start = (datetime.strptime(args.start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
             if args.start else datetime.now(timezone.utc))
    simulation = Simulation(SiteConfig(seed=args.seed, clouds_enabled=not args.no_clouds))
    simulation.tick(start, 0.0)  # registers exist before the first client connects
    threading.Thread(target=simulation.run_forever, args=(start,), daemon=True).start()
    if args.opcua_port:
        start_opcua(simulation, args.host, args.opcua_port)
    server = Server((args.host, args.port), lambda unit: simulation.registers.get(unit), args.verbose)
    log("simulator serving units %s on %s:%d, simulated start %s, seed %d"
        % (sorted(simulation.registers), args.host, args.port, start.strftime("%Y-%m-%d %H:%M:%SZ"), args.seed))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("stopping")
        return 0


if __name__ == "__main__":
    sys.exit(main())
