"""What this driver contributes to the anonymous daily report.

Free of Home Assistant imports on purpose, so the payload can be checked
without a Home Assistant installation. Everything here is either the charger's
rating or an on/off fact about how it is wired up.

Deliberately absent: how much was charged and how often. A charger's energy is
easy to read and tempting to report, but a daily kWh figure next to an
approximate position says more about a household's car than a maintainer needs
to know, and session counts say more still.

See https://stats.rnet.se/integritet for the full list and the reasoning.
"""

from __future__ import annotations

from typing import Any

#: The unit this driver speaks to. Fixed, never taken from the device.
MODEL = "ctek_ccu"


def _truthy(value: Any) -> bool:
    """The CCU answers with booleans, strings and numbers depending on the
    firmware. Only the shapes that clearly mean yes count as yes."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "on", "connected", "1"}
    return False


def build_extra(
    *,
    connectors: int,
    max_current_a: int,
    control_enabled: bool,
    charging_allowed: bool,
    backend_connected: Any = None,
    nanogrid: Any = None,
    rfid: Any = None,
    had_error: bool = False,
) -> dict[str, Any]:
    """Assemble the driver's part of the report."""
    metrics: dict[str, float] = {}
    if max_current_a:
        metrics["charger_a"] = round(float(max_current_a))
    if connectors:
        metrics["connectors"] = int(connectors)

    return {
        "models": [MODEL],
        "features": {
            # Whether the driver may write, and whether it currently allows
            # charging: the safety gate is the whole point of this driver.
            "control": bool(control_enabled),
            "charging_allowed": bool(charging_allowed),
            # How the charger is wired up. Whether an OCPP backend and a
            # Ferroamp nanogrid are in play decides which limit actually wins,
            # so knowing how common each is says what to test against.
            "backend": _truthy(backend_connected),
            "nanogrid": _truthy(nanogrid),
            "rfid": _truthy(rfid),
        },
        "metrics": metrics,
        "errors": 1 if had_error else 0,
    }
