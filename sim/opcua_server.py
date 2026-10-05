"""OPC UA server for the plant controller (ADR 0007 decision 5, ADR 0010). Needs asyncua (sim/requirements.txt).

Publishes the five nodes of sim.plant_controller.PlantController under an object named PlantController. The node IDs are
text: ns=2;s=PlantController.POI_MW and so on, where the namespace index follows the namespace URI below. Clients write
ActivePowerLimit_MW and LimitEnable; the server applies them to the plant controller and writes the accepted values back.

Writes are picked up by polling twice a second rather than by a write callback: simple, and a limit that is half a second
late is far inside the simulator's own one-second tick. No security (anonymous, no encryption): dev only, ADR 0010.
"""
import asyncio

from asyncua import Server, ua

NAMESPACE_URI = "urn:fleet-scada:simulator"
OBJECT_NAME = "PlantController"
ENDPOINT_PATH = "/fleet-scada/sim"
SYNC_PERIOD_S = 0.5
WRITABLE = ("ActivePowerLimit_MW", "LimitEnable")
VARIANT_TYPES = {
    "ActivePowerLimit_MW": ua.VariantType.Double,
    "LimitEnable": ua.VariantType.Boolean,
    "LimitActive": ua.VariantType.Boolean,
    "POI_MW": ua.VariantType.Double,
    "Status": ua.VariantType.String,
}


def endpoint_url(host, port):
    return "opc.tcp://%s:%d%s" % (host, port, ENDPOINT_PATH)


async def serve(controller, host, port, log=print, started=None):
    """Run the server until cancelled. `started` (an asyncio.Event) is set once clients can connect."""
    server = Server()
    await server.init()
    server.set_endpoint(endpoint_url(host, port))
    server.set_server_name("Fleet SCADA simulator")
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
    namespace = await server.register_namespace(NAMESPACE_URI)
    folder = await server.nodes.objects.add_object(namespace, OBJECT_NAME)

    nodes = {}
    readings = controller.readings()
    for name, variant_type in VARIANT_TYPES.items():
        node_id = ua.NodeId("%s.%s" % (OBJECT_NAME, name), namespace)
        nodes[name] = await folder.add_variable(node_id, name, readings[name], variant_type)
        if name in WRITABLE:
            await nodes[name].set_writable()

    async def write(name, value):
        await nodes[name].write_value(ua.Variant(value, VARIANT_TYPES[name]))

    async with server:
        log("OPC UA plant controller at %s (namespace %s, %d nodes)" % (endpoint_url(host, port), NAMESPACE_URI, len(nodes)))
        if started is not None:
            started.set()
        last = {name: readings[name] for name in WRITABLE}  # what this server last put in the writable nodes
        while True:
            seen = {name: await nodes[name].read_value() for name in WRITABLE}
            if seen != last:  # a client wrote one of them
                limit_mw, enabled = controller.command(seen["ActivePowerLimit_MW"], seen["LimitEnable"])
                accepted = {"ActivePowerLimit_MW": limit_mw, "LimitEnable": enabled}
                for name in WRITABLE:
                    if seen[name] != accepted[name]:
                        await write(name, accepted[name])  # show what was really accepted (a clamped limit)
                last = accepted
                log("plant controller command: limit %.3f MW, enabled %s" % (limit_mw, enabled))
            for name, value in controller.readings().items():
                if name not in WRITABLE:
                    await write(name, value)
            await asyncio.sleep(SYNC_PERIOD_S)
