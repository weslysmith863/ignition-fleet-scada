"""The plant controller's six OPC UA nodes as plain Python (ADR 0007, decision 5; RatedMW added in Phase 2). Standard library only.

The OPC UA server (sim/opcua_server.py) is a thin front for this class: it publishes `readings()` and passes written
setpoints to `command()`. The behavior lives here so it can be tested without an OPC UA library.

Nodes: ActivePowerLimit_MW (write), LimitEnable (write), LimitActive (read), POI_MW (read), Status (read), RatedMW (read).
RatedMW is the plant's AC rating. Unlike ActivePowerLimit_MW, which rests at the rating while no limit is set but moves with
one, it never changes, so a screen can use it as the scale for the limit and for the plant output.
A plant with a battery (ADR 0016) has two more nodes, both writable: BatteryMode (Idle, Charge, or Discharge) and
BatterySetpoint_MW (the size of the power, never negative). A plant without one has exactly the six above.
Reactive power is not modeled; the plant runs at unity power factor (approximated, ADR 0007).
"""
import math


class PlantController:
    def __init__(self, simulation):
        self._simulation = simulation
        config = simulation.config
        self.rated_mw = config.inverters * config.inverter_ac_w / 1e6
        self.limit_mw = self.rated_mw  # a disabled limit sits at the rating, so it never reads as a restriction
        self.enabled = False
        self.has_battery = config.has_battery

    def command(self, limit_mw, enable):
        """Accept the setpoints a client wrote. The limit is held between 0 and the plant rating, and a value that is not
        a finite number is ignored (the previous limit stays). Returns the accepted (limit_mw, enabled) so the server can
        write them back and the client sees what was really accepted."""
        if isinstance(limit_mw, (int, float)) and not isinstance(limit_mw, bool) and math.isfinite(limit_mw):
            self.limit_mw = min(max(float(limit_mw), 0.0), self.rated_mw)
        self.enabled = bool(enable)
        self._simulation.model.set_limit(self.limit_mw, self.enabled)
        return self.limit_mw, self.enabled

    def command_battery(self, mode, setpoint_mw):
        """Accept the battery nodes a client wrote (ADR 0016 decision 6). Returns the accepted (mode, setpoint in MW); a mode
        that is not Idle, Charge, or Discharge and a setpoint that is not a finite number are ignored, and the setpoint is held
        between 0 and the battery's rating. Without a battery there is nothing to command."""
        if not self.has_battery:
            return "Idle", 0.0
        return self._simulation.model.set_battery(mode, setpoint_mw)

    def readings(self):
        """The values of all six nodes, from the latest simulation tick.

        LimitActive is true only while the limit is actually reducing output: an enabled limit above what the plant
        could produce changes nothing. That is what separates curtailment from clipping. Status is a design choice:
        Curtailed while the limit is active, Producing while there is output, Standby otherwise (sun down)."""
        state = self._simulation.state
        poi_mw = state["poi_w"] / 1e6
        limit_active = bool(state["limit_binding"])
        if limit_active:
            status = "Curtailed"
        elif poi_mw > 0.0:
            status = "Producing"
        else:
            status = "Standby"
        nodes = {
            "ActivePowerLimit_MW": self.limit_mw,
            "LimitEnable": self.enabled,
            "LimitActive": limit_active,
            "POI_MW": poi_mw,
            "Status": status,
            "RatedMW": self.rated_mw,
        }
        if self.has_battery:
            nodes["BatteryMode"] = state["battery_mode"]
            nodes["BatterySetpoint_MW"] = state["battery_setpoint_w"] / 1e6
        return nodes
