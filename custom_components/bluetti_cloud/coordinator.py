"""Data update coordinator for Bluetti Cloud — MQTT+REST hybrid.

MQTT provides real-time telemetry (~1s) for battery SOC, pack voltage/current,
charging status, and switch states. REST API provides power readings (PV/AC/DC/Grid),
energy totals, and online status at a slower interval (60s when MQTT is active,
30s as fallback).

Active MQTT polling sends FC=03 read requests for homeData (reg 100),
PackMainInfo (reg 6000), and PackItemInfo (reg 6100) per battery pack.
The device only sends data when explicitly asked via these read commands.

Data merge rule: MQTT data takes precedence for fields it provides (more current);
REST fills in fields MQTT cannot provide.
"""

import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import BluettiCloudApi, BluettiCloudApiError
from .api.modbus import CHARGING_STATUS_MAP
from .api.mqtt_client import BluettiMqttClient
from .api.profiles import DeviceProfile, get_profile
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DEVICE_STALE_AFTER,
    DOMAIN,
)
from .mqtt_manager import BluettiMqttManager

_LOGGER = logging.getLogger(__name__)

# Typed config entry: entry.runtime_data is the coordinator (PEP 695 alias is
# lazily evaluated, so the forward reference to the class below is fine).
type BluettiConfigEntry = ConfigEntry[BluettiCloudCoordinator]


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


def is_device_reachable(device_data: dict[str, Any]) -> bool:
    """True if the device has produced real data recently enough to trust.

    There is no dependable power-state signal in the cloud API — the V2 ctrl
    power bit reads 0 on a device that is powered on, and REST sessionState
    reports Offline for devices whose MQTT link is working. So reachability is
    judged by whether the device has actually been heard from.
    """
    last_seen = device_data.get("last_seen")
    if not last_seen:
        # Never established a contact time. Some devices never provide one —
        # an AC300's REST telemetry is all-null and its MQTT link may be down —
        # so treating that as unreachable would hide entities that work. Only
        # a device we HAVE heard from and then lost is considered unreachable.
        return True
    return (time.time() - last_seen) < DEVICE_STALE_AFTER


def _normalize_iot_session(value: Any) -> str | None:
    """Normalize the API's iotSession field to "Online"/"Offline"/None.

    The AC300 reports "Online"/null; the AP300 reports "1". Both indicate the
    device's cloud IoT session state, so map any online indicator to "Online".
    """
    if value is None or value == "":
        return None
    if str(value).lower() in ("1", "online", "true"):
        return "Online"
    return "Offline"


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
            # PackMainInfo fields (from active polling):
            "pack_total_voltage": float | None,
            "pack_total_current": float | None,
            "pack_total_soc": int | None,
            "pack_total_soh": int | None,
            "pack_average_temp": int | None,
            "charge_full_time": int | None,
            "discharge_empty_time": int | None,
            # Per-pack fields (dynamic, from active polling):
            "pack_1_voltage": float | None,
            "pack_1_current": float | None,
            "pack_1_soc": int | None,
            "pack_1_soh": int | None,
            "pack_1_temp": int | None,
            "pack_1_charging_status": str | None,
            # ... pack_2_*, pack_3_*, etc.
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
        # Cache last known data so entities don't go unavailable on transient errors
        self._last_good_data: dict[str, dict[str, Any]] = {}
        # Per-device profile (data path, registers, switch semantics), resolved
        # from the model + protocol version on each REST refresh.
        self._profiles: dict[str, DeviceProfile] = {}
        # MQTT manager owns the real-time telemetry half of the integration
        self._mqtt = BluettiMqttManager(self)

    @property
    def client(self) -> BluettiCloudApi:
        return self._client

    def profile_for(self, sn: str) -> DeviceProfile:
        """Return the resolved device profile for a device SN.

        Falls back to resolving from the configured model (protocol version 0)
        if a REST refresh has not populated the profile yet.
        """
        profile = self._profiles.get(sn)
        if profile is not None:
            return profile
        model = self._device_info.get(sn, {}).get("model", "")
        return get_profile(model, 0)

    # -- MQTT delegation --
    #
    # The MQTT half lives in BluettiMqttManager; the coordinator owns the
    # manager and exposes a thin delegating surface so entities and __init__
    # keep working against the coordinator object.

    @property
    def mqtt_client(self) -> BluettiMqttClient | None:
        return self._mqtt.mqtt_client

    @property
    def mqtt_connected(self) -> bool:
        return self._mqtt.mqtt_connected

    @property
    def _mqtt_client(self) -> BluettiMqttClient | None:
        return self._mqtt._mqtt_client

    @_mqtt_client.setter
    def _mqtt_client(self, value: BluettiMqttClient | None) -> None:
        self._mqtt._mqtt_client = value

    @property
    def _mqtt_connected(self) -> bool:
        return self._mqtt._mqtt_connected

    @_mqtt_connected.setter
    def _mqtt_connected(self, value: bool) -> None:
        self._mqtt._mqtt_connected = value

    @property
    def _mqtt_data(self) -> dict[str, dict[str, Any]]:
        """Per-device MQTT overlay dict, owned by the manager."""
        return self._mqtt.overlays

    def get_pack_count(self, sn: str) -> int:
        """Return the discovered pack count for a device."""
        return self._mqtt.get_pack_count(sn)

    def register_new_pack_callback(self, callback: Callable[[str, int], None]) -> None:
        """Register a callback for when new battery packs are discovered.

        Callback signature: (device_sn: str, pack_count: int) -> None
        """
        self._mqtt.register_new_pack_callback(callback)

    def register_node_callback(
        self, callback: Callable[[str, list[dict[str, Any]]], None]
    ) -> None:
        """Register a callback for when new sub-device nodes are discovered."""
        self._mqtt.register_node_callback(callback)

    def get_nodes(self, sn: str) -> list[dict[str, Any]]:
        """Return the last known sub-device node list for a device."""
        return self._mqtt.get_nodes(sn)

    async def async_start_mqtt(self) -> None:
        """Start MQTT client and subscribe to device telemetry topics."""
        await self._mqtt.async_start()

    def async_stop_mqtt(self) -> None:
        """Disconnect MQTT client, cancel reconnection, and clean up."""
        self._mqtt.async_stop()

    def _schedule_reconnect(self) -> None:
        """Schedule MQTT reconnection with exponential backoff."""
        self._mqtt._schedule_reconnect()

    # -- REST data fetching --

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch data from the Bluetti Cloud API (periodic REST poll)."""
        # Check MQTT status and handle reconnection
        if self._mqtt_connected and self._mqtt_client and not self._mqtt_client.is_connected:
            # Connection dropped mid-session — clean up and schedule reconnect
            _LOGGER.warning("MQTT disconnected — scheduling reconnection")
            self._mqtt._cleanup_mqtt_client()
            self.update_interval = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
            self._schedule_reconnect()

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
            iot_session = _normalize_iot_session(
                last_alive_embedded.get("iotSession")
            )

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

            # Resolve and cache the device profile (data path, registers,
            # switch semantics) from the model + reported protocol version.
            self._profiles[sn] = get_profile(
                device_data["device_type"],
                _safe_int(dev.get("factoryProtocolVer")) or 0,
            )

            # Fetch detailed telemetry
            try:
                alive_data = await self._client.get_device_last_alive(sn)
                if alive_data and not alive_data.get("allFieldIsNull"):
                    # Real telemetry means the cloud has heard from the device.
                    device_data["last_seen"] = time.time()
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

                    # REST-only devices (e.g. AP300) source aggregate battery
                    # voltage and charging status from getDeviceLastAlive; MQTT
                    # devices get these from the overlay below, which takes
                    # precedence. Voltage feeds the "Battery Total Voltage"
                    # sensor (data_key pack_total_voltage). Charging status uses
                    # the V2 map (codes 0-5); the AP300 is a protocolVer-2015
                    # device, so codes 3/4/5 (idle/AC/solar) must decode too.
                    voltage = _safe_float(alive_data.get("batteryVoltage"))
                    if voltage is not None:
                        device_data["pack_total_voltage"] = voltage

                    charge_raw = _safe_int(alive_data.get("packChargingStatus"))
                    if charge_raw is not None:
                        device_data["charging_status"] = CHARGING_STATUS_MAP.get(
                            charge_raw, f"unknown({charge_raw})"
                        )

                    ts = alive_data.get("timestamp")
                    if ts:
                        device_data["last_update"] = ts

                    iot = _normalize_iot_session(alive_data.get("iotSession"))
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

            # Keep the most recent contact time from either transport.
            previous = self._last_good_data.get(sn, {}).get("last_seen")
            if previous and previous > device_data.get("last_seen", 0):
                device_data["last_seen"] = previous

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
