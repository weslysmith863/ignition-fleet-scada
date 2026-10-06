# ADR 0013: The simulator runs as a Compose service named sim

Status: Accepted (2026-10-05). Carries out decision D24 and ADR 0006.

## Context

Until now the simulator ran as a Python program in a terminal on the PC, and the gateways reached it through
`host.docker.internal`, Docker Desktop's name for the PC. That needs a person to start it, needs the PC's `.venv`, and does not
work the same on another machine (Linux has no such name unless it is added). The goal is `docker compose up` and everything runs.

## Decision

1. **A fourth Compose service, `sim`,** built from `sim/Dockerfile` (`python:3.14-slim`, `asyncua` from `sim/requirements.txt`, run
   as an ordinary user). One process serves Modbus on 15020 and the OPC UA plant controller on 14840 (ADR 0010). A health check
   passes when both ports accept a connection. `.dockerignore` allows only `sim/` into the build, so `.env` and the `.venv` can
   never end up in an image.
2. **The gateways reach it as `sim:15020` and `sim:14840`** over the Compose network, the same pattern as `postgres:5432`. The
   points list's `host` column is `sim`, and `python -m generator.retarget` moves the existing devices and the
   `PlantController` OPC connection onto it. Retarget changes only host and port, and only when told to (`--apply`).
3. **The ports are also published on the PC's loopback** (`127.0.0.1:15020` and `127.0.0.1:14840`) so tools on the PC, such as the
   OPC UA test client, can still reach it. Nothing is exposed beyond the PC.
4. **`SIM_START`** (optional, from `.env`) pins the simulated start time, so the plant is producing every time the container
   starts. Empty means the real clock, and the plant sleeps at night. The command-line `--start` still wins when given.

## Consequences

- During the move both paths work (the published port and the service name), so the gateways need not be offline.
- The simulated clock restarts at `SIM_START` every time the container starts, so the energy counter and the clouds start over.
  History already in PostgreSQL is kept; new rows continue from the new simulated time but are stamped by the gateway's real clock.
- Anyone cloning the repo runs `docker compose up -d --build` and gets all four containers. The OPC UA server still has no
  security (ADR 0010).
- The OPC UA server is told to listen on `0.0.0.0` in the container, so the endpoint it advertises names `0.0.0.0`. The gateway
  connects with the host in its configured URL, as it did with `127.0.0.1` before (finding 28), and this was confirmed to work when the connection moved (finding 35).
- Running the simulator from a terminal is still possible for development (stop the container first, because both want the same
  ports).
