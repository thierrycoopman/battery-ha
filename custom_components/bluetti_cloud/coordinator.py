"""Data update coordinator for Bluetti Cloud — MQTT+REST hybrid.

MQTT provides real-time telemetry (~1s) for battery SOC, pack voltage/current,
charging status, and switch states. REST API provides power readings (PV/AC/DC/Grid),
energy totals, and online status at a slower interval (60s when MQTT is active,
30s as fallback).

Data merge rule: MQTT data takes precedence for fields it provides (more current);
REST fills in fields MQTT cannot provide.
"""

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import BluettiCloudApi, BluettiCloudApiError
from .api.modbus import (
    AC_SWITCH,
    DC_SWITCH,
    FUNC_READ_HOLDING,
    FUNC_WRITE_SINGLE,
    parse_home_data,
)
from .api.mqtt_client import BluettiMqttClient, BluettiMqttError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MQTT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


def _safe_float(value: Any) -> float | None:
    """Convert to float, returning None only when value is absent."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> int | None:
    """Convert to int, returning None only when value is absent."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _is_on(value: Any) -> bool | None:
    """Convert switch value to bool. Returns None if value is absent."""
    if value is None:
        return None
    return str(value) not in ("0", "", "false", "False", "None")


# Fields that MQTT homeData can provide (used for merge)
_MQTT_SENSOR_FIELDS = {
    "battery_soc", "pack_voltage", "pack_current",
    "charging_status", "charging_status_raw",
    "charge_time_remaining", "discharge_time_remaining",
    "pack_count", "inverter_count",
}

# Switch state fields from MQTT ctrl_status bits
_MQTT_SWITCH_MAP = {
    "ctrl_ac_switch": "ac_switch",
    "ctrl_dc_switch": "dc_switch",
    "ctrl_pv_switch": "pv_switch",
    "ctrl_grid_switch": "grid_switch",
}

# Register address to switch data key (for FC=06 write echo)
_REGISTER_TO_SWITCH = {
    AC_SWITCH: "ac_switch",
    DC_SWITCH: "dc_switch",
}


class BluettiCloudCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator that combines MQTT telemetry with REST API polling.

    Data structure per device:
        {
            "online": bool,
            "iot_session": str | None,
            "device_name": str,
            "device_type": str,
            "sub_sn": str,
            "battery_soc": int | None,
            "pack_voltage": float | None,      # MQTT
            "pack_current": float | None,       # MQTT
            "charging_status": str | None,      # MQTT
            "charge_time_remaining": int | None, # MQTT (minutes)
            "discharge_time_remaining": int | None, # MQTT (minutes)
            "pack_count": int | None,           # MQTT
            "inverter_count": int | None,       # MQTT
            "power_pv_in": float | None,
            "power_grid_in": float | None,
            "power_ac_out": float | None,
            "power_dc_out": float | None,
            "power_feed_back": float | None,
            "ac_switch": bool | None,
            "dc_switch": bool | None,
            "pv_switch": bool | None,
            "grid_switch": bool | None,
            "energy_day": float | None,
            "energy_month": float | None,
            "energy_year": float | None,
            "energy_total": float | None,
            "last_update": str | None,
            "mqtt_active": bool,               # whether MQTT is providing data
        }
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: BluettiCloudApi,
        device_sns: list[str],
        device_info: dict[str, dict[str, str]],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self._client = client
        self._device_sns = device_sns
        self._device_info = device_info
        self._mqtt_client: BluettiMqttClient | None = None
        self._mqtt_connected = False
        # Per-device MQTT data overlay (accumulated between REST refreshes)
        self._mqtt_data: dict[str, dict[str, Any]] = {}
        # Map PUB topic -> device SN for incoming telemetry routing
        self._topic_to_sn: dict[str, str] = {}
        # Cache last known data so entities don't go unavailable on transient errors
        self._last_good_data: dict[str, dict[str, Any]] = {}

    @property
    def client(self) -> BluettiCloudApi:
        return self._client

    @property
    def mqtt_client(self) -> BluettiMqttClient | None:
        return self._mqtt_client

    @property
    def mqtt_connected(self) -> bool:
        return self._mqtt_connected and self._mqtt_client is not None and self._mqtt_client.is_connected

    # -- MQTT lifecycle --

    async def async_start_mqtt(self) -> None:
        """Start MQTT client and subscribe to device telemetry topics.

        Called after the first REST refresh so we have device model/subSn data.
        Two-phase connect: async HTTP on HA loop, then blocking paho in executor.
        """
        if self._mqtt_client and self._mqtt_client.is_connected:
            return

        token = self._client._token
        if not token:
            raise BluettiMqttError("API not authenticated — cannot start MQTT")

        self._mqtt_client = BluettiMqttClient(
            session=self._client._session,
            token=token,
            loop=self.hass.loop,
            on_telemetry=self._handle_mqtt_message,
        )

        # Phase 1: async HTTP work (certs + TOTP) on HA event loop
        prep = await self._mqtt_client.async_prepare()

        # Phase 2: blocking TCP+TLS connect in executor thread
        await self.hass.async_add_executor_job(
            self._mqtt_client.connect_blocking, prep
        )

        self._mqtt_connected = True

        # Subscribe to telemetry for all configured devices
        if self.data:
            for sn, dev_data in self.data.items():
                model = dev_data.get("device_type", "")
                sub_sn = dev_data.get("sub_sn", "")
                if model and sub_sn:
                    topic = f"PUB/{model}/{sub_sn}"
                    self._topic_to_sn[topic] = sn
                    self._mqtt_client.subscribe_telemetry(model, sub_sn)

        # Slow down REST polling since MQTT handles real-time data
        self.update_interval = timedelta(seconds=MQTT_SCAN_INTERVAL)
        _LOGGER.info(
            "MQTT telemetry active — REST interval increased to %ds",
            MQTT_SCAN_INTERVAL,
        )

    def async_stop_mqtt(self) -> None:
        """Disconnect MQTT client and clean up."""
        if self._mqtt_client:
            self._mqtt_client.disconnect()
            self._mqtt_client.cleanup_pem_files()
            self._mqtt_client = None
        self._mqtt_connected = False
        self._topic_to_sn.clear()
        # Restore faster REST polling
        self.update_interval = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

    # -- MQTT message handling --

    def _handle_mqtt_message(self, topic: str, parsed: dict) -> None:
        """Handle an incoming parsed MQTT message. Runs on HA event loop."""
        sn = self._topic_to_sn.get(topic)
        if not sn:
            _LOGGER.debug("MQTT message on unknown topic: %s", topic)
            return

        fc = parsed.get("function_code")

        if fc == FUNC_READ_HOLDING:
            self._handle_telemetry_data(sn, parsed)
        elif fc == FUNC_WRITE_SINGLE:
            self._handle_write_echo(sn, parsed)

    def _handle_telemetry_data(self, sn: str, parsed: dict) -> None:
        """Process FC=03 homeData telemetry frame."""
        register_data = parsed.get("register_data", b"")
        if not register_data:
            return

        home_data = parse_home_data(register_data)
        if not home_data:
            return

        _LOGGER.debug(
            "MQTT homeData for %s: soc=%s voltage=%s current=%s status=%s",
            sn,
            home_data.get("battery_soc"),
            home_data.get("pack_voltage"),
            home_data.get("pack_current"),
            home_data.get("charging_status"),
        )

        # Accumulate MQTT data for this device
        mqtt_overlay = self._mqtt_data.setdefault(sn, {})

        # Copy sensor fields
        for field in _MQTT_SENSOR_FIELDS:
            if field in home_data:
                mqtt_overlay[field] = home_data[field]

        # Map ctrl_status bits to switch state fields
        for ctrl_key, switch_key in _MQTT_SWITCH_MAP.items():
            if ctrl_key in home_data:
                mqtt_overlay[switch_key] = home_data[ctrl_key]

        mqtt_overlay["mqtt_active"] = True

        # Push update to HA entities immediately
        self._push_mqtt_update()

    def _handle_write_echo(self, sn: str, parsed: dict) -> None:
        """Process FC=06 write echo (switch command confirmation)."""
        reg = parsed.get("register_addr")
        val = parsed.get("value")
        if reg is None or val is None:
            return

        switch_key = _REGISTER_TO_SWITCH.get(reg)
        if not switch_key:
            return

        new_state = val != 0
        _LOGGER.debug(
            "MQTT write echo for %s: %s = %s (reg=%d val=%d)",
            sn, switch_key, new_state, reg, val,
        )

        mqtt_overlay = self._mqtt_data.setdefault(sn, {})
        mqtt_overlay[switch_key] = new_state
        mqtt_overlay["mqtt_active"] = True

        self._push_mqtt_update()

    def _push_mqtt_update(self) -> None:
        """Merge MQTT overlay into current data and push to HA entities.

        Note: We do NOT update _last_good_data here — that is only set by
        the REST refresh cycle to avoid mixing stale REST + fresh MQTT data
        in the error fallback cache.
        """
        if not self.data:
            return

        merged = {}
        for sn, device_data in self.data.items():
            merged_device = dict(device_data)
            mqtt_overlay = self._mqtt_data.get(sn)
            if mqtt_overlay:
                merged_device.update(mqtt_overlay)
            merged[sn] = merged_device

        # Notify all entities with merged data (does not affect _last_good_data)
        self.async_set_updated_data(merged)

    # -- REST data fetching --

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch data from the Bluetti Cloud API (periodic REST poll)."""
        # Check if MQTT disconnected unexpectedly — restore faster REST polling
        if self._mqtt_connected and self._mqtt_client and not self._mqtt_client.is_connected:
            _LOGGER.warning(
                "MQTT disconnected — restoring REST interval to %ds",
                DEFAULT_SCAN_INTERVAL,
            )
            self._mqtt_connected = False
            self.update_interval = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

        try:
            all_devices = await self._client.get_devices()
        except BluettiCloudApiError as err:
            if self._last_good_data:
                _LOGGER.warning(
                    "Error fetching devices, using cached data: %s", err
                )
                return self._last_good_data
            raise UpdateFailed(f"Error fetching device list: {err}") from err

        # Build lookup from homeDevices response
        cloud_lookup: dict[str, dict[str, Any]] = {}
        for dev in all_devices:
            sn = dev.get("sn", "")
            if sn in self._device_sns:
                cloud_lookup[sn] = dev

        result: dict[str, dict[str, Any]] = {}

        for sn in self._device_sns:
            info = self._device_info.get(sn, {})
            dev = cloud_lookup.get(sn)

            if dev is None:
                cached = self._last_good_data.get(sn)
                if cached:
                    result[sn] = {**cached, "online": False}
                else:
                    result[sn] = self._empty_device_data(sn, info)
                continue

            last_alive_embedded = dev.get("lastAlive") or {}
            session_state = dev.get("sessionState", "")
            is_online = (
                session_state.lower() == "online" if session_state else False
            )
            iot_session = last_alive_embedded.get("iotSession")

            device_data: dict[str, Any] = {
                "online": is_online,
                "iot_session": iot_session,
                "device_name": info.get("name", dev.get("name", sn)),
                "device_type": info.get("model", dev.get("model", "")),
                "sub_sn": dev.get("subSn", ""),
                "battery_soc": _safe_int(
                    last_alive_embedded.get("batterySoc") or dev.get("batSOC")
                ),
                "pack_voltage": None,
                "pack_current": None,
                "charging_status": None,
                "charge_time_remaining": None,
                "discharge_time_remaining": None,
                "pack_count": None,
                "inverter_count": None,
                "power_pv_in": _safe_float(last_alive_embedded.get("powerPvIn")),
                "power_grid_in": _safe_float(last_alive_embedded.get("powerGridIn")),
                "power_ac_out": _safe_float(last_alive_embedded.get("powerAcOut")),
                "power_dc_out": _safe_float(last_alive_embedded.get("powerDcOut")),
                "power_feed_back": _safe_float(last_alive_embedded.get("powerFeedBack")),
                "ac_switch": _is_on(last_alive_embedded.get("acSwitch")),
                "dc_switch": _is_on(last_alive_embedded.get("dcSwitch")),
                "pv_switch": _is_on(last_alive_embedded.get("pvSwitch")),
                "grid_switch": _is_on(last_alive_embedded.get("gridSwitch")),
                "energy_day": None,
                "energy_month": None,
                "energy_year": None,
                "energy_total": None,
                "last_update": last_alive_embedded.get("timestamp"),
                "mqtt_active": False,
            }

            # Fetch detailed telemetry
            try:
                alive_data = await self._client.get_device_last_alive(sn)
                if alive_data and not alive_data.get("allFieldIsNull"):
                    soc = _safe_int(alive_data.get("batterySoc"))
                    if soc is not None:
                        device_data["battery_soc"] = soc

                    for field, key in [
                        ("powerPvIn", "power_pv_in"),
                        ("powerGridIn", "power_grid_in"),
                        ("powerAcOut", "power_ac_out"),
                        ("powerDcOut", "power_dc_out"),
                        ("powerFeedBack", "power_feed_back"),
                    ]:
                        val = _safe_float(alive_data.get(field))
                        if val is not None:
                            device_data[key] = val

                    for field, key in [
                        ("acSwitch", "ac_switch"),
                        ("dcSwitch", "dc_switch"),
                        ("pvSwitch", "pv_switch"),
                        ("gridSwitch", "grid_switch"),
                    ]:
                        val = _is_on(alive_data.get(field))
                        if val is not None:
                            device_data[key] = val

                    ts = alive_data.get("timestamp")
                    if ts:
                        device_data["last_update"] = ts

                    iot = alive_data.get("iotSession")
                    if iot:
                        device_data["iot_session"] = iot

            except BluettiCloudApiError:
                _LOGGER.debug("Failed to get live telemetry for %s", sn)

            # Fetch energy totals
            try:
                energy = await self._client.get_energy_detail(sn)
                if energy:
                    device_data["energy_day"] = _safe_float(energy.get("day"))
                    device_data["energy_month"] = _safe_float(energy.get("month"))
                    device_data["energy_year"] = _safe_float(energy.get("year"))
                    device_data["energy_total"] = _safe_float(energy.get("total"))
            except BluettiCloudApiError:
                _LOGGER.debug("Failed to get energy detail for %s", sn)

            # Overlay MQTT data (takes precedence for fields it provides)
            mqtt_overlay = self._mqtt_data.get(sn)
            if mqtt_overlay:
                device_data.update(mqtt_overlay)

            result[sn] = device_data

        self._last_good_data = result
        return result

    def _empty_device_data(
        self, sn: str, info: dict[str, str]
    ) -> dict[str, Any]:
        """Return a device data dict with all values set to None/defaults."""
        return {
            "online": False,
            "iot_session": None,
            "device_name": info.get("name", sn),
            "device_type": info.get("model", ""),
            "sub_sn": "",
            "battery_soc": None,
            "pack_voltage": None,
            "pack_current": None,
            "charging_status": None,
            "charge_time_remaining": None,
            "discharge_time_remaining": None,
            "pack_count": None,
            "inverter_count": None,
            "power_pv_in": None,
            "power_grid_in": None,
            "power_ac_out": None,
            "power_dc_out": None,
            "power_feed_back": None,
            "ac_switch": None,
            "dc_switch": None,
            "pv_switch": None,
            "grid_switch": None,
            "energy_day": None,
            "energy_month": None,
            "energy_year": None,
            "energy_total": None,
            "last_update": None,
            "mqtt_active": False,
        }
