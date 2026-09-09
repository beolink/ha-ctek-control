# CTEK CCU Control

A local-API driver for a CTEK Charge Control Unit (CCU), giving Home Assistant
an allow / block / throttle surface for EV charging — designed to pair with
[EMS Steward](https://github.com/beolink/ha-ems).

## Why this instead of taking over OCPP

A charge point speaks OCPP to exactly one central system. Where that is an
inverter (e.g. a Ferroamp EnergyHub doing dynamic load balancing), pointing the
charger at Home Assistant instead would hand you scheduling but **lose the
upstream fuse protection**.

This driver avoids the trade-off. It writes an OCPP `TxDefaultProfile` through
the CCU's own local REST API. OCPP composes stacked profiles by taking the
**lowest** limit, so the driver can only ever restrict further than the upstream
system already allows — never exceed it. The charger keeps its OCPP link and its
load balancing; EMS just decides *when* charging is permitted.

## Entities

| Entity | Purpose |
|---|---|
| `switch.<prefix>_control_enabled` | Master gate — while off, nothing is written to the charger |
| `switch.<prefix>_charging_allowed` | Bind as EMS's EV charger entity: on = charging permitted (limit = current), off = blocked (0 A) |
| `number.<prefix>_charging_current` | Bind as EMS's EV current entity; capped by the configured maximum |
| `sensor.<prefix>_control_status` | Last limit sent, plus diagnostics |
| `sensor.<prefix>_active_limit` | The limit actually binding the charger — including whatever the upstream central system applies |
| `sensor.<prefix>_outlet_N_state` | Per-connector state read from the charger |
| `binary_sensor.<prefix>_backend_connected` | Whether the charger's OCPP backend link is up |
| `sensor.<prefix>_firmware`, `_serial`, `_diagnostics` | Device info and raw endpoint payloads (disabled by default) |

Values are polled from the CCU's read-only endpoints every 30 seconds. Response
shapes vary between firmware revisions, so the sensors match on key *name*
rather than a fixed path, and the diagnostics sensor exposes the raw payloads so
the typed sensors can be tightened against a real installation.

## Setup

Settings → Devices & Services → Add Integration → **CTEK CCU Control**, then
enter the CCU's address, its login, the number of connectors and a maximum
charging current. Credentials are entered by you and stored by Home Assistant.

The CCU serves HTTPS with a self-signed certificate; verification is disabled
for that local host by design.

## One session at a time

The CCU accepts only **one** session. A second login while one is open — the
owner's own browser included — is answered with HTTP 500, and a session that is
never closed holds the slot indefinitely. This driver therefore borrows the
session for each poll and **always logs out again**, so the web UI stays usable
between polls. Polling is deliberately slow (120 s) for the same reason, and a
failed login backs off instead of retrying every cycle.

If the charger starts answering 500 to every login, a session is stuck open:
log out of the web UI, or power-cycle the CCU to clear it.

## Safety

- The control gate defaults **off**.
- The requested current is always capped by the configured maximum.
- Turning the gate off restores the configured maximum, handing the charger
  back to the upstream system.

## Anonymous statistics

The driver sends one report per day to <https://stats.rnet.se>: which version
you run, your Home Assistant version and installation type, the country you have
set in Home Assistant, an approximate position rounded to about 11 km, the
charger's rated current, how many connectors it has and its firmware version,
whether control is enabled and charging currently allowed, and whether an OCPP backend, a Ferroamp
nanogrid and RFID are in play.

**Deliberately not** how much you charged or how often. The meter is right there
and easy to read, but a daily kWh figure next to an approximate position says
more about a household's car than a maintainer needs to know, and session counts
say more still. What is useful is which limit actually wins in the field:
whether an upstream backend or a nanogrid is composing with this driver's
profile, and how many installations dare to enable control at all.

It never sends a name, an address, an exact position, a serial number or an
entity name, and your IP address is not stored.

To opt out: *Settings, Devices and services, CTEK CCU, Configure, Send anonymous
usage statistics.* Switching it off also erases what has already been sent. The
full list of fields and the reasoning: <https://stats.rnet.se/integritet>.
Run `python3 tests/test_stats.py` to check the payload rules yourself.

## License

MIT
