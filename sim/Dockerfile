# The plant simulator as a container (ADR 0013). Build context is the repo root: docker compose build sim
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first, so a code change does not reinstall them. asyncua is only needed for the OPC UA plant controller.
COPY sim/requirements.txt sim/requirements.txt
RUN pip install --no-cache-dir -r sim/requirements.txt

COPY sim/ sim/

# Run as an ordinary user, not root.
RUN useradd --system --uid 10001 sim
USER sim

# Modbus TCP and OPC UA. Inside the container the server listens on every interface; Compose decides what is published.
EXPOSE 15020 14840

# SIM_START (an optional UTC time such as 2026-10-05T17:00:00Z) pins the simulated start; without it the real clock is used.
CMD ["python", "-m", "sim.modbus_server", "--host", "0.0.0.0", "--port", "15020", "--opcua-port", "14840"]
