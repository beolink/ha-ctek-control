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

## Safety

- The control gate defaults **off**.
- The requested current is always capped by the configured maximum.
- Turning the gate off restores the configured maximum, handing the charger
  back to the upstream system.

## License

MIT
