"""Throwaway Modbus TCP server for the Phase 1 scale-factor spike (ADR 0006). Standard library only.

Answers function 3 (read holding registers) for unit IDs 1 and 2. Each unit holds a SunSpec model 103 block at the
usual base address 40000, with the SunSpec "SunS" marker and common-model header in front of it, so the register
positions match the public model: W at +14, W_SF at +15, Hz at +16, Hz_SF at +17 from the model's ID register.
Every request is logged (unit, first address, count) so we can see which addresses Ignition actually asks for.
Addresses are the 0-based protocol addresses that go on the wire.
"""
import socketserver
import struct
import sys
import time

BASE = 40000
MODEL_ID_ADDR = BASE + 70  # model 103 header follows 'SunS' (2) + common model 1 (2 header + 66 body)


def sunspec_map(w_raw, w_sf, hz_raw, hz_sf):
    regs = {BASE: 0x5375, BASE + 1: 0x6E53}  # 'SunS'
    regs[BASE + 2], regs[BASE + 3] = 1, 66  # common model header: ID 1, length 66
    regs[MODEL_ID_ADDR], regs[MODEL_ID_ADDR + 1] = 103, 50  # model 103 header: ID, length
    regs[MODEL_ID_ADDR + 14] = w_raw & 0xFFFF
    regs[MODEL_ID_ADDR + 15] = w_sf & 0xFFFF  # sunssf is a signed 16-bit value
    regs[MODEL_ID_ADDR + 16] = hz_raw & 0xFFFF
    regs[MODEL_ID_ADDR + 17] = hz_sf & 0xFFFF
    return regs


# Different scale factors per unit, so a correct read proves both the unit ID and the scaling.
UNITS = {
    1: sunspec_map(w_raw=4200, w_sf=1, hz_raw=6000, hz_sf=-2),   # 42000 W, 60.00 Hz
    2: sunspec_map(w_raw=1234, w_sf=-1, hz_raw=5998, hz_sf=-2),  # 123.4 W, 59.98 Hz
}


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class Handler(socketserver.BaseRequestHandler):
    def recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.request.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def handle(self):
        log("connection from %s:%d" % self.client_address)
        while True:
            head = self.recv_exact(7)  # MBAP: transaction, protocol, length, unit
            if head is None:
                log("connection closed")
                return
            tid, proto, length, unit = struct.unpack(">HHHB", head)
            pdu = self.recv_exact(length - 1)
            if pdu is None:
                return
            fc = pdu[0]
            if fc == 3 and len(pdu) >= 5:
                start, count = struct.unpack(">HH", pdu[1:5])
                if unit not in UNITS:
                    log("unit %d  FC3  start=%d count=%d  -> exception 0x0B (no such unit)" % (unit, start, count))
                    resp = bytes([0x83, 0x0B])
                else:
                    regs = UNITS[unit]
                    values = [regs.get(start + i, 0) for i in range(count)]
                    log("unit %d  FC3  start=%d count=%d" % (unit, start, count))
                    resp = bytes([3, count * 2]) + b"".join(struct.pack(">H", v) for v in values)
            else:
                log("unit %d  FC%d  unsupported -> exception 0x01" % (unit, fc))
                resp = bytes([fc | 0x80, 0x01])
            self.request.sendall(struct.pack(">HHHB", tid, proto, len(resp) + 1, unit) + resp)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5020
    log("serving units %s on %s:%d" % (sorted(UNITS), host, port))
    Server((host, port), Handler).serve_forever()
