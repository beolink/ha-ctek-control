"""Status sensor: what the driver last sent, and whether the CCU is reachable."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CcuCoordinator, active_limit_a, dig
from .device import ccu_device_info
from .runtime import CtekRuntime


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    rt: CtekRuntime = data["runtime"]
    coordinator: CcuCoordinator = data["coordinator"]
    async_add_entities([
        CtekStatusSensor(rt),
        CtekActiveLimitSensor(coordinator, rt),
        CtekFirmwareSensor(coordinator, rt),
        CtekSerialSensor(coordinator, rt),
        CtekDiagnosticsSensor(coordinator, rt),
    ] + [
        CtekOutletStateSensor(coordinator, rt, c)
        for c in range(1, rt.connectors + 1)
    ])


class CtekStatusSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:information-outline"
    _attr_translation_key = "control_status"

    def __init__(self, runtime: CtekRuntime) -> None:
        self._rt = runtime
        self._attr_unique_id = f"{runtime.entry_id}_control_status"
        self.entity_id = f"sensor.{runtime.prefix}_control_status"
        self._attr_device_info = ccu_device_info(runtime.entry_id)

    @property
    def native_value(self) -> str:
        if self._rt.last_error:
            return "error"
        if not self._rt.control_enabled:
            return "disabled"
        if self._rt.last_command is None:
            return "idle"
        return "blocked" if self._rt.last_command == 0 else f"limit {self._rt.last_command} A"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "control_enabled": self._rt.control_enabled,
            "charging_allowed": self._rt.charging_allowed,
            "requested_current_a": self._rt.current_a,
            "max_current_a": self._rt.max_current_a,
            "last_limit_sent_a": self._rt.last_command,
            "connectors": self._rt.connectors,
            "last_error": self._rt.last_error,
        }


class _CcuSensor(CoordinatorEntity[CcuCoordinator], SensorEntity):
    """Base for values read back from the charger."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CcuCoordinator, runtime: CtekRuntime,
                 key: str, suffix: str | None = None) -> None:
        super().__init__(coordinator)
        self._rt = runtime
        self._attr_translation_key = key
        self._attr_unique_id = f"{runtime.entry_id}_{suffix or key}"
        self.entity_id = f"sensor.{runtime.prefix}_{suffix or key}"
        self._attr_device_info = ccu_device_info(runtime.entry_id)


class CtekActiveLimitSensor(_CcuSensor):
    """The lowest limit the charger is actually bound by — including whatever
    the upstream central system applies, not just what this driver sent."""

    _attr_native_unit_of_measurement = "A"
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator, runtime) -> None:
        super().__init__(coordinator, runtime, "active_limit")

    @property
    def native_value(self):
        return active_limit_a((self.coordinator.data or {}).get("profiles"))


class CtekOutletStateSensor(_CcuSensor):
    """Per-connector state as reported by the charger (charging, available…)."""

    _attr_icon = "mdi:ev-plug-type2"

    def __init__(self, coordinator, runtime, connector: int) -> None:
        super().__init__(coordinator, runtime, "outlet_state", f"outlet_{connector}_state")
        self._connector = connector
        self._attr_translation_placeholders = {"connector": str(connector)}

    @property
    def native_value(self):
        outlets = (self.coordinator.data or {}).get("outlets")
        if outlets is None:
            return None
        if isinstance(outlets, list) and len(outlets) >= self._connector:
            item = outlets[self._connector - 1]
            if isinstance(item, dict):
                return dig(item, "state", "status", "outletstate", "connectorstatus")
            return item
        return dig(outlets, f"outlet{self._connector}", "state", "status")


class CtekFirmwareSensor(_CcuSensor):
    _attr_icon = "mdi:chip"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, runtime) -> None:
        super().__init__(coordinator, runtime, "firmware")

    @property
    def native_value(self):
        return dig((self.coordinator.data or {}).get("fw"), "version", "fwversion", "value")


class CtekSerialSensor(_CcuSensor):
    _attr_icon = "mdi:identifier"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, runtime) -> None:
        super().__init__(coordinator, runtime, "serial")

    @property
    def native_value(self):
        return dig((self.coordinator.data or {}).get("serial"), "serialno", "serial", "value")


class CtekDiagnosticsSensor(_CcuSensor):
    """Raw payloads from every polled endpoint, as attributes.

    Response shapes vary by firmware; this exposes exactly what the CCU returns
    so the typed sensors above can be tightened against a real installation.
    """

    _attr_icon = "mdi:code-json"
    _attr_entity_registry_enabled_default = False
    _unrecorded_attributes = frozenset({"outlets", "nanogrid", "mil", "profiles", "rfid"})

    def __init__(self, coordinator, runtime) -> None:
        super().__init__(coordinator, runtime, "diagnostics")

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        return f"{sum(1 for v in data.values() if v is not None)}/{len(data)} endpoints"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self.coordinator.data or {})
