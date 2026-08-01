"""MQTT manager for Bluetti Cloud.

Owns the real-time MQTT half of the integration: connection lifecycle,
reconnection with exponential backoff, active FC=03 polling, and parsing of
incoming telemetry (FC=03 responses, FC=16 data pushes, and FC=06 write echoes)
into a per-device overlay that the coordinator merges onto its REST baseline.

MQTT provides real-time telemetry (~1s) for battery SOC, pack voltage/current,
charging status, and switch states. The device only sends data when explicitly
asked via read commands, so an active polling loop drives homeData (reg 100),
PackMainInfo (reg 6000), and PackItemInfo (reg 6100) per battery pack.

Data merge rule: MQTT data takes precedence for fields it provides (more
current); REST fills in fields MQTT cannot provide.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from .api.modbus import (
    AC_SWITCH,
    DC_SWITCH,
    EXCEPTION_ILLEGAL_DATA_ADDRESS,
    FUNC_READ_HOLDING,
    FUNC_WRITE_MULTIPLE,
    FUNC_WRITE_SINGLE,
    HOME_DATA,
    HOME_DATA_COUNT,
    IOT_PAYLOAD_VER_V2,
    NODE_INFO,
    PACK_ITEM_INFO,
    PACK_ITEM_INFO_COUNT,
    PACK_MAIN_INFO,
    PACK_MAIN_INFO_COUNT,
    PACK_SELECT,
    parse_fc16_registers,
    parse_home_data,
    parse_node_info,
    parse_pack_item_info,
    parse_pack_main_info,
)
from .api.mqtt_client import BluettiMqttClient, BluettiMqttError
from .const import (
    DEFAULT_SCAN_INTERVAL,
    MQTT_POLL_INTERVAL,
    MQTT_RECONNECT_MAX,
    MQTT_RECONNECT_MIN,
    MQTT_REQUEST_TIMEOUT,
    MQTT_SCAN_INTERVAL,
)

if TYPE_CHECKING:
    from .coordinator import BluettiCloudCoordinator

_LOGGER = logging.getLogger(__name__)


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


class BluettiMqttManager:
    """Owns the MQTT client, reconnection, polling, and telemetry parsing.

    The manager keeps a back-reference to the coordinator so it can read the
    current device data (``coordinator.data``), the api client, and the Home
    Assistant instance, and can push merged updates back to entities.
    """

    def __init__(self, coordinator: BluettiCloudCoordinator) -> None:
        self._coordinator = coordinator
        self._mqtt_client: BluettiMqttClient | None = None
        self._mqtt_connected = False
        # Per-device MQTT data overlay (accumulated between REST refreshes)
        self.overlays: dict[str, dict[str, Any]] = {}
        # Map PUB topic -> device SN for incoming telemetry routing
        self._topic_to_sn: dict[str, str] = {}

        # -- MQTT reconnection state --
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_delay: int = MQTT_RECONNECT_MIN
        self._stopping: bool = False

        # -- Active MQTT polling state --
        self._poll_task: asyncio.Task | None = None
        # Pending request tracking for response routing
        self._pending_request: tuple[int, int] | None = None  # (register, slave_addr)
        self._response_event: asyncio.Event = asyncio.Event()
        self._response_data: bytes | None = None
        # Discovered pack counts per device (for dynamic sensor creation)
        # This tracks actually connected packs (not hardware slots)
        self._pack_counts: dict[str, int] = {}
        # Hardware max pack slots per device (from pack_num_max register)
        self._pack_slots: dict[str, int] = {}
        # Which pack IDs have been seen with real data (non-zero voltage/SOC)
        self._discovered_packs: dict[str, set[int]] = {}
        # Devices that send FC=16 data pushes (V1 protocol) — skip homeData/FC=03
        self._fc16_devices: set[str] = set()
        # Callbacks for new pack discovery
        self._new_pack_callbacks: list[Callable[[str, int], None]] = []
        # Sub-device (NODE_INFO) discovery: seen node slave addrs + callbacks
        self._discovered_nodes: dict[str, set[int]] = {}
        self._node_callbacks: list[Callable[[str, list[dict[str, Any]]], None]] = []
        # Registers that returned Modbus errors — skip in future polls
        # Key: sn, Value: set of (register, slave_addr) tuples
        self._unsupported_registers: dict[str, set[tuple[int, int]]] = {}

    @property
    def hass(self):
        return self._coordinator.hass

    @property
    def mqtt_client(self) -> BluettiMqttClient | None:
        return self._mqtt_client

    @property
    def mqtt_connected(self) -> bool:
        return (
            self._mqtt_connected
            and self._mqtt_client is not None
            and self._mqtt_client.is_connected
        )

    def get_pack_count(self, sn: str) -> int:
        """Return the discovered pack count for a device."""
        return self._pack_counts.get(sn, 0)

    def register_new_pack_callback(self, callback: Callable[[str, int], None]) -> None:
        """Register a callback for when new battery packs are discovered.

        Callback signature: (device_sn: str, pack_count: int) -> None
        """
        self._new_pack_callbacks.append(callback)

    def register_node_callback(
        self, callback: Callable[[str, list[dict[str, Any]]], None]
    ) -> None:
        """Register a callback for when new sub-device nodes are discovered.

        Callback signature: (device_sn: str, nodes: list[dict]) -> None
        """
        self._node_callbacks.append(callback)

    def get_nodes(self, sn: str) -> list[dict[str, Any]]:
        """Return the last known sub-device node list for a device."""
        return self.overlays.get(sn, {}).get("nodes", [])

    # -- MQTT lifecycle --

    def _has_mqtt_devices(self) -> bool:
        """True if any configured device uses the MQTT data path."""
        data = self._coordinator.data or {}
        return any(
            self._coordinator.profile_for(sn).data_path == "mqtt+rest"
            for sn in data
        )

    async def async_start(self) -> None:
        """Start MQTT client and subscribe to device telemetry topics.

        Called after the first REST refresh so we have device model/subSn data.
        Two-phase connect: async HTTP on HA loop, then blocking paho in executor.
        Each attempt uses a fresh token and fresh P12 certs/TOTP to avoid
        stale credential issues.
        """
        if self._mqtt_client and self._mqtt_client.is_connected:
            return

        # Skip MQTT entirely if no configured device uses it (e.g. an all
        # REST-only setup like the AP300). Avoids pointless broker connections.
        if not self._has_mqtt_devices():
            _LOGGER.debug("No MQTT-capable devices configured — staying REST-only")
            return

        client = self._coordinator.client

        # Use the latest token (REST polling may have refreshed it)
        token = client._token
        if not token:
            raise BluettiMqttError("API not authenticated — cannot start MQTT")

        # Clean up any previous client before creating a new one
        self._cleanup_mqtt_client()

        self._mqtt_client = BluettiMqttClient(
            session=client._session,
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
        self._reconnect_delay = MQTT_RECONNECT_MIN  # Reset backoff on success

        # Subscribe to telemetry for MQTT-capable devices only. REST-only
        # devices (e.g. AP300) do not speak this protocol, so skip them.
        if self._coordinator.data:
            for sn, dev_data in self._coordinator.data.items():
                if self._coordinator.profile_for(sn).data_path != "mqtt+rest":
                    continue
                model = dev_data.get("device_type", "")
                sub_sn = dev_data.get("sub_sn", "")
                if model and sub_sn:
                    topic = f"PUB/{model}/{sub_sn}"
                    self._topic_to_sn[topic] = sn
                    self._mqtt_client.subscribe_telemetry(model, sub_sn)

        # Slow down REST polling since MQTT handles real-time data for the
        # MQTT devices. But if any configured device is REST-only, keep the
        # faster interval — REST is its ONLY data source and it must not be
        # slowed by an unrelated MQTT-capable device sharing this coordinator.
        has_rest_only = any(
            self._coordinator.profile_for(sn).data_path == "rest_only"
            for sn in (self._coordinator.data or {})
        )
        interval = DEFAULT_SCAN_INTERVAL if has_rest_only else MQTT_SCAN_INTERVAL
        self._coordinator.update_interval = timedelta(seconds=interval)
        _LOGGER.info("MQTT telemetry active — REST interval set to %ds", interval)

        # Start active polling loop
        self._start_polling()

    def _cleanup_mqtt_client(self) -> None:
        """Clean up MQTT client and polling task without affecting reconnection."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            self._poll_task = None
        if self._mqtt_client:
            self._mqtt_client.disconnect()
            self._mqtt_client.cleanup_pem_files()
            self._mqtt_client = None
        self._mqtt_connected = False

    def _start_polling(self) -> None:
        """Start the active MQTT polling task."""
        if self._poll_task and not self._poll_task.done():
            return
        self._poll_task = self.hass.async_create_task(
            self._polling_loop(), "bluetti_mqtt_poll"
        )

    def async_stop(self) -> None:
        """Disconnect MQTT client, cancel reconnection, and clean up."""
        self._stopping = True
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None
        self._cleanup_mqtt_client()
        self._topic_to_sn.clear()
        # Restore faster REST polling
        self._coordinator.update_interval = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

    def _schedule_reconnect(self) -> None:
        """Schedule MQTT reconnection with exponential backoff.

        Safe to call multiple times — only starts one reconnect loop.
        """
        if self._stopping:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return  # Already reconnecting
        self._reconnect_task = self.hass.async_create_task(
            self._reconnect_loop(), "bluetti_mqtt_reconnect"
        )

    async def _reconnect_loop(self) -> None:
        """Retry MQTT connection with exponential backoff (30s → 60s → 120s → 300s).

        Each attempt uses fresh credentials (token, P12 cert, TOTP) since these
        are time-sensitive. On success, resets the backoff delay. On failure,
        doubles the delay up to MQTT_RECONNECT_MAX.
        """
        try:
            while not self._stopping:
                _LOGGER.info(
                    "MQTT reconnect scheduled in %ds", self._reconnect_delay
                )
                await asyncio.sleep(self._reconnect_delay)

                if self._stopping:
                    break

                try:
                    await self.async_start()
                    _LOGGER.info("MQTT reconnected successfully")
                    return  # Success — exit the loop
                except Exception:
                    _LOGGER.warning(
                        "MQTT reconnect failed — next attempt in %ds",
                        min(self._reconnect_delay * 2, MQTT_RECONNECT_MAX),
                        exc_info=True,
                    )
                    # Clean up the failed attempt
                    self._cleanup_mqtt_client()
                    # Exponential backoff
                    self._reconnect_delay = min(
                        self._reconnect_delay * 2, MQTT_RECONNECT_MAX
                    )
        except asyncio.CancelledError:
            _LOGGER.debug("MQTT reconnect loop cancelled")

    # -- Active MQTT polling --

    async def _polling_loop(self) -> None:
        """Periodically send FC=03 read requests for all devices.

        Sends requests sequentially: homeData, PackMainInfo, then PackItemInfo
        for each known battery pack. Waits for each response before sending next.
        """
        _LOGGER.debug("MQTT polling loop started (interval=%ds)", MQTT_POLL_INTERVAL)
        try:
            while True:
                if not self.mqtt_connected:
                    _LOGGER.debug("MQTT not connected, skipping poll cycle")
                    await asyncio.sleep(MQTT_POLL_INTERVAL)
                    continue

                for sn, dev_data in (self._coordinator.data or {}).items():
                    if self._coordinator.profile_for(sn).data_path != "mqtt+rest":
                        continue

                    model = dev_data.get("device_type", "")
                    sub_sn = dev_data.get("sub_sn", "")
                    if not model or not sub_sn:
                        continue

                    # FC=16 devices (AC300, V1 protocol) push data automatically
                    # via FC=16 frames — no need to send FC=03 read requests
                    if sn in self._fc16_devices:
                        continue

                    profile = self._coordinator.profile_for(sn)
                    if profile.iot_payload_ver >= IOT_PAYLOAD_VER_V2:
                        # 2nd-gen IoT poll device (AP300): homeData (reg 100)
                        # provides aggregate SOC/voltage/charging/switch state.
                        # Per-pack blocks (PackMainInfo/PackItemInfo) are a
                        # follow-up (#5). Uses slave 0 + the V2 payload envelope.
                        await self._poll_register(
                            sn, model, sub_sn, HOME_DATA, HOME_DATA_COUNT,
                            slave_addr=profile.slave_addr,
                            payload_ver=profile.iot_payload_ver,
                        )
                        # Enumerate sub-devices (batteries, D1/A1 hubs) via the
                        # NODE_INFO query-write.
                        await self._poll_node_info(
                            sn, model, sub_sn, profile.iot_payload_ver
                        )
                    else:
                        # Legacy V1 poll path (slave 1, 0x01 framing).
                        await self._poll_register(
                            sn, model, sub_sn, HOME_DATA, HOME_DATA_COUNT
                        )
                        await self._poll_register(
                            sn, model, sub_sn, PACK_MAIN_INFO, PACK_MAIN_INFO_COUNT
                        )
                        pack_count = self._pack_counts.get(sn, 0)
                        for pack_idx in range(1, pack_count + 1):
                            await self._poll_register(
                                sn, model, sub_sn, PACK_ITEM_INFO,
                                PACK_ITEM_INFO_COUNT, slave_addr=pack_idx,
                            )

                await asyncio.sleep(MQTT_POLL_INTERVAL)
        except asyncio.CancelledError:
            _LOGGER.debug("MQTT polling loop cancelled")
        except Exception:
            _LOGGER.exception("MQTT polling loop crashed")

    async def _poll_node_info(
        self, sn: str, model: str, sub_sn: str, payload_ver: float
    ) -> None:
        """Send a NODE_INFO query-write and wait for the sub-device list reply."""
        if not self._mqtt_client or not self._mqtt_client.is_connected:
            return

        self._pending_request = (NODE_INFO, 0)
        self._response_event.clear()
        try:
            self._mqtt_client.send_node_query(model, sub_sn, 1, payload_ver)
        except BluettiMqttError:
            _LOGGER.debug("Failed to send node query for %s", sn)
            self._pending_request = None
            return

        try:
            await asyncio.wait_for(
                self._response_event.wait(), timeout=MQTT_REQUEST_TIMEOUT
            )
        except TimeoutError:
            _LOGGER.debug("Timeout waiting for node info: %s", sn)
        finally:
            self._pending_request = None

    async def _poll_register(
        self,
        sn: str,
        model: str,
        sub_sn: str,
        register: int,
        count: int,
        slave_addr: int = 1,
        payload_ver: float = 1.0,
    ) -> None:
        """Send a single FC=03 read request and wait for response."""
        if not self._mqtt_client or not self._mqtt_client.is_connected:
            return

        # Skip registers that previously returned Modbus errors
        unsupported = self._unsupported_registers.get(sn, set())
        if (register, slave_addr) in unsupported:
            return

        # Set up pending request tracking
        self._pending_request = (register, slave_addr)
        self._response_event.clear()
        self._response_data = None

        try:
            self._mqtt_client.send_read_request(
                model, sub_sn, register, count, slave_addr, payload_ver
            )
        except BluettiMqttError:
            _LOGGER.debug(
                "Failed to send read request for %s reg=%d slave=%d",
                sn, register, slave_addr,
            )
            self._pending_request = None
            return

        # Wait for response
        try:
            await asyncio.wait_for(
                self._response_event.wait(), timeout=MQTT_REQUEST_TIMEOUT
            )
        except TimeoutError:
            _LOGGER.debug(
                "Timeout waiting for response: %s reg=%d slave=%d",
                sn, register, slave_addr,
            )
        finally:
            self._pending_request = None

    # -- MQTT message handling --

    def _handle_mqtt_message(self, topic: str, parsed: dict) -> None:
        """Handle an incoming parsed MQTT message. Runs on HA event loop."""
        sn = self._topic_to_sn.get(topic)
        if not sn:
            _LOGGER.debug("MQTT message on unknown topic: %s", topic)
            return

        fc = parsed.get("function_code")

        if parsed.get("is_error"):
            self._handle_error_response(sn, parsed)
        elif fc == FUNC_READ_HOLDING:
            self._handle_telemetry_data(sn, parsed)
        elif fc == FUNC_WRITE_MULTIPLE:
            self._handle_write_multiple_data(sn, parsed)
        elif fc == FUNC_WRITE_SINGLE:
            self._handle_write_echo(sn, parsed)

    def _handle_telemetry_data(self, sn: str, parsed: dict) -> None:
        """Process FC=03 response, routing to correct parser based on pending request."""
        register_data = parsed.get("register_data", b"")
        if not register_data:
            return

        # Determine which parser to use based on pending request
        pending = self._pending_request
        if pending is not None:
            register, slave_addr = pending
        else:
            # No pending request — assume homeData (passive response / unsolicited)
            register = HOME_DATA
            slave_addr = 1

        self._route_register_data(sn, register, slave_addr, register_data)

        # Signal the polling loop that a response arrived
        self._response_data = register_data
        self._response_event.set()

    def _handle_write_multiple_data(self, sn: str, parsed: dict) -> None:
        """Process FC=0x10 data push from device.

        Bluetti devices push telemetry using the FC=16 (Write Multiple Registers)
        frame format, which includes start_addr — allowing us to route to the
        correct parser without relying on pending request tracking.

        Two parsing paths:
        1. AC300 register map (parse_fc16_registers): extracts fields from raw
           register addresses (0, 36, 70, 130, 3000) — works for all V1 devices.
        2. V2 register routing (_route_register_data): routes to V2 parsers when
           start_addr matches V2 register constants (100, 6000, 6100).

        Only signals the response event if start_addr matches the pending
        request's register, to avoid unsolicited pushes from prematurely
        unblocking the polling loop.
        """
        register_data = parsed.get("register_data", b"")
        start_addr = parsed.get("start_addr")
        if not register_data or start_addr is None:
            return

        # NODE_INFO (reg 21000) replies arrive as FC=0x10 too, but carry the
        # sub-device list, not telemetry registers — route them separately.
        if start_addr == NODE_INFO:
            self._process_node_info(sn, register_data)
            pending = self._pending_request
            if pending is not None and pending[0] == NODE_INFO:
                self._response_event.set()
            return

        _LOGGER.debug(
            "MQTT FC=16 data for %s: start_addr=%d, %d bytes",
            sn, start_addr, len(register_data),
        )

        # Parse using AC300 register map (actual register addresses)
        self._process_fc16_data(sn, start_addr, register_data)

        # Also route to V2 parsers if start_addr matches V2 register addresses
        slave_addr = 1
        pending = self._pending_request
        if pending is not None:
            slave_addr = pending[1]

        self._route_register_data(sn, start_addr, slave_addr, register_data)

        # Only signal response event if this matches the pending request
        if pending is not None and start_addr == pending[0]:
            self._response_data = register_data
            self._response_event.set()

    def _handle_error_response(self, sn: str, parsed: dict) -> None:
        """Process Modbus error response (FC with bit 7 set, e.g. 0x83).

        Logs the error, records the register as unsupported to skip future
        polls, and signals the response event so the polling loop doesn't timeout.
        """
        exception_code = parsed.get("exception_code", 0)
        original_fc = parsed.get("original_fc", 0)
        pending = self._pending_request

        if pending is not None:
            register, slave_addr = pending
            _LOGGER.debug(
                "MQTT error for %s: FC=0x%02X reg=%d slave=%d exception=0x%02X "
                "(%s) — marking as unsupported",
                sn, original_fc, register, slave_addr, exception_code,
                "illegal data address" if exception_code == EXCEPTION_ILLEGAL_DATA_ADDRESS
                else f"code {exception_code}",
            )
            # Track this register as unsupported to skip in future polls
            unsupported = self._unsupported_registers.setdefault(sn, set())
            unsupported.add((register, slave_addr))
        else:
            _LOGGER.debug(
                "MQTT error for %s (no pending request): FC=0x%02X exception=0x%02X",
                sn, original_fc, exception_code,
            )

        # Signal the polling loop so it doesn't waste time on timeout
        self._response_event.set()

    def _process_node_info(self, sn: str, register_data: bytes) -> None:
        """Parse a NODE_INFO reply and store the sub-device list in the overlay."""
        nodes = parse_node_info(register_data)
        if not nodes:
            return
        _LOGGER.debug(
            "MQTT node info for %s: %d nodes (%s)",
            sn, len(nodes), ", ".join(n["model_name"] for n in nodes),
        )
        mqtt_overlay = self.overlays.setdefault(sn, {})
        mqtt_overlay["nodes"] = nodes
        mqtt_overlay["mqtt_active"] = True

        # Notify listeners when previously-unseen nodes appear (dynamic entities)
        seen = self._discovered_nodes.setdefault(sn, set())
        new_addrs = {n["slave_addr"] for n in nodes} - seen
        if new_addrs:
            seen |= new_addrs
            for cb in self._node_callbacks:
                try:
                    cb(sn, nodes)
                except Exception:
                    _LOGGER.exception("Error in node discovery callback")

        self._push_mqtt_update()

    def _route_register_data(
        self, sn: str, register: int, slave_addr: int, register_data: bytes
    ) -> None:
        """Route register data to the appropriate parser based on register address."""
        if register == HOME_DATA:
            self._process_home_data(sn, register_data)
        elif register == PACK_MAIN_INFO:
            self._process_pack_main_info(sn, register_data)
        elif register == PACK_ITEM_INFO:
            self._process_pack_item_info(sn, register_data, slave_addr)

    def _process_home_data(self, sn: str, register_data: bytes) -> None:
        """Parse and store homeData fields.

        Skipped entirely for FC=16 devices (AC300, protocolVer < 2001) because
        register 100 has a different layout — the V2 parser produces garbage
        values (soc=36, charging_status=5760, charge_time=0, discharge_time=1).
        """
        # FC=16 devices get their data from register pushes, not homeData
        if sn in self._fc16_devices:
            _LOGGER.debug("Skipping homeData for %s (FC=16 device)", sn)
            return

        home_data = parse_home_data(register_data)
        if not home_data:
            return

        # Additional validation: reject if charging_status is not a known code
        raw_status = home_data.get("charging_status_raw")
        if raw_status is not None and raw_status > 10:
            _LOGGER.debug(
                "Skipping homeData for %s: invalid charging_status_raw=%d",
                sn, raw_status,
            )
            return

        _LOGGER.debug(
            "MQTT homeData for %s: soc=%s voltage=%s current=%s status=%s",
            sn,
            home_data.get("battery_soc"),
            home_data.get("pack_voltage"),
            home_data.get("pack_current"),
            home_data.get("charging_status"),
        )

        mqtt_overlay = self.overlays.setdefault(sn, {})

        for field in _MQTT_SENSOR_FIELDS:
            if field in home_data:
                mqtt_overlay[field] = home_data[field]

        for ctrl_key, switch_key in _MQTT_SWITCH_MAP.items():
            if ctrl_key in home_data:
                mqtt_overlay[switch_key] = home_data[ctrl_key]

        # homeData carries the aggregate battery voltage/current; surface them
        # via the "Battery Total Voltage"/"Current" sensors (pack_total_*). For
        # V1 FC=16 devices these come from PackMainInfo instead; this block only
        # runs for poll-driven devices (FC=16 devices are skipped above).
        if "pack_voltage" in home_data:
            mqtt_overlay["pack_total_voltage"] = home_data["pack_voltage"]
        if "pack_current" in home_data:
            mqtt_overlay["pack_total_current"] = home_data["pack_current"]

        mqtt_overlay["mqtt_active"] = True
        self._push_mqtt_update()

    def _process_pack_main_info(self, sn: str, register_data: bytes) -> None:
        """Parse and store PackMainInfo fields."""
        pack_main = parse_pack_main_info(register_data)
        if not pack_main:
            return

        _LOGGER.debug(
            "MQTT PackMainInfo for %s: total_soc=%s total_v=%s packs=%s",
            sn,
            pack_main.get("pack_total_soc"),
            pack_main.get("pack_total_voltage"),
            pack_main.get("pack_count"),
        )

        mqtt_overlay = self.overlays.setdefault(sn, {})

        # Store pack summary fields
        for field in (
            "pack_total_voltage", "pack_total_current",
            "pack_total_soc", "pack_total_soh",
            "pack_average_temp", "charge_full_time", "discharge_empty_time",
            "pack_charging_status_text",
        ):
            if field in pack_main:
                mqtt_overlay[field] = pack_main[field]

        # Track pack count for dynamic sensor creation
        pack_count = pack_main.get("pack_count", 0)
        if pack_count and pack_count != self._pack_counts.get(sn, 0):
            old_count = self._pack_counts.get(sn, 0)
            self._pack_counts[sn] = pack_count
            _LOGGER.info(
                "Device %s: discovered %d battery packs (was %d)",
                sn, pack_count, old_count,
            )
            for cb in self._new_pack_callbacks:
                try:
                    cb(sn, pack_count)
                except Exception:
                    _LOGGER.exception("Error in new pack callback")

        mqtt_overlay["mqtt_active"] = True
        self._push_mqtt_update()

    def _process_pack_item_info(
        self, sn: str, register_data: bytes, slave_addr: int
    ) -> None:
        """Parse and store per-battery PackItemInfo fields."""
        pack_item = parse_pack_item_info(register_data)
        if not pack_item:
            return

        # Use pack_id from response data if available, else fall back to slave_addr
        pack_id = pack_item.get("pack_id", slave_addr)

        _LOGGER.debug(
            "MQTT PackItemInfo for %s pack %d: soc=%s v=%s i=%s",
            sn, pack_id,
            pack_item.get("pack_soc"),
            pack_item.get("pack_voltage"),
            pack_item.get("pack_current"),
        )

        mqtt_overlay = self.overlays.setdefault(sn, {})

        # Store per-pack data with pack_N_ prefix
        prefix = f"pack_{pack_id}_"
        field_map = {
            "pack_voltage": "voltage",
            "pack_current": "current",
            "pack_soc": "soc",
            "pack_soh": "soh",
            "pack_average_temp": "temp",
            "pack_charging_status_text": "charging_status",
        }
        for src_key, dst_suffix in field_map.items():
            if src_key in pack_item:
                mqtt_overlay[f"{prefix}{dst_suffix}"] = pack_item[src_key]

        mqtt_overlay["mqtt_active"] = True
        self._push_mqtt_update()

    def _process_fc16_data(
        self, sn: str, start_addr: int, register_data: bytes
    ) -> None:
        """Parse FC=16 register block using the AC300 register map.

        Maps raw Modbus register values to coordinator data keys.
        Handles per-pack data cycling: when pack data arrives (start_addr=70),
        stores it under pack_{N}_ keys, then advances to the next pack by
        writing register 3006.
        """
        fields = parse_fc16_registers(start_addr, register_data)
        if not fields:
            return

        # Mark this device as FC=16 (V1 protocol) — skip homeData/FC=03 for it
        self._fc16_devices.add(sn)

        mqtt_overlay = self.overlays.setdefault(sn, {})

        # Map FC=16 field names to coordinator data keys
        _FC16_FIELD_MAP = {
            "total_battery_percent": "battery_soc",
            "dc_input_power": "power_pv_in",
            "ac_input_power": "power_grid_in",
            "ac_output_power": "power_ac_out",
            "dc_output_power": "power_dc_out",
            "ac_output_on": "ac_switch",
            "dc_output_on": "dc_switch",
            "ctrl_ac_switch": "ac_switch",
            "ctrl_dc_switch": "dc_switch",
            "charging_status": "charging_status",
        }

        for src_key, dst_key in _FC16_FIELD_MAP.items():
            if src_key in fields:
                mqtt_overlay[dst_key] = fields[src_key]

        # Populate pack_total_* fields (aggregate values)
        if "total_battery_voltage" in fields:
            mqtt_overlay["pack_total_voltage"] = fields["total_battery_voltage"]
        if "total_battery_current" in fields:
            mqtt_overlay["pack_total_current"] = fields["total_battery_current"]
        if "total_battery_percent" in fields:
            mqtt_overlay["pack_total_soc"] = fields["total_battery_percent"]

        # Track hardware pack slots (pack_num_max)
        pack_num_max = fields.get("pack_num_max")
        if pack_num_max and pack_num_max > 0:
            self._pack_slots[sn] = pack_num_max

        # Handle per-pack data and cycling
        pack_num = fields.get("pack_num")
        if pack_num is not None and pack_num > 0:
            self._process_per_pack_data(sn, pack_num, fields)

        if _LOGGER.isEnabledFor(logging.DEBUG):
            logged_fields = {k: v for k, v in fields.items()
                           if k not in ("pack_status_raw",)}
            _LOGGER.debug("FC=16 parsed for %s addr=%d: %s", sn, start_addr, logged_fields)

        mqtt_overlay["mqtt_active"] = True
        self._push_mqtt_update()

    def _process_per_pack_data(
        self, sn: str, pack_num: int, fields: dict[str, Any]
    ) -> None:
        """Store per-pack data and advance pack cycling.

        When data arrives for pack N, stores it under pack_{N}_ keys.
        Then writes register 3006 to select the next pack, so the next
        FC=16 push at start_addr=70 will contain that pack's data.
        """
        mqtt_overlay = self.overlays.setdefault(sn, {})
        prefix = f"pack_{pack_num}_"

        if "pack_voltage" in fields:
            mqtt_overlay[f"{prefix}voltage"] = fields["pack_voltage"]
        if "pack_battery_percent" in fields:
            mqtt_overlay[f"{prefix}soc"] = fields["pack_battery_percent"]
        if "charging_status" in fields:
            mqtt_overlay[f"{prefix}charging_status"] = fields["charging_status"]

        # Track which packs have real data (non-zero voltage or SOC)
        pack_voltage = fields.get("pack_voltage", 0)
        pack_soc = fields.get("pack_battery_percent", 0)
        if pack_voltage > 0 or pack_soc > 0:
            discovered = self._discovered_packs.setdefault(sn, set())
            was_new = pack_num not in discovered
            discovered.add(pack_num)

            # Update pack_count based on actually connected packs
            connected_count = len(discovered)
            if connected_count != self._pack_counts.get(sn, 0):
                self._pack_counts[sn] = connected_count
                if was_new:
                    _LOGGER.info(
                        "Device %s: discovered battery pack %d "
                        "(soc=%s%% voltage=%sV, %d packs total)",
                        sn, pack_num, pack_soc, pack_voltage, connected_count,
                    )
                    for cb in self._new_pack_callbacks:
                        try:
                            cb(sn, connected_count)
                        except Exception:
                            _LOGGER.exception("Error in new pack callback")

        # Advance to next pack for cycling
        pack_slots = self._pack_slots.get(sn, 0)
        if pack_slots > 1:
            next_pack = (pack_num % pack_slots) + 1
            self._send_pack_select(sn, next_pack)

    def _send_pack_select(self, sn: str, pack_num: int) -> None:
        """Write register 3006 to select which pack reports in registers 96-99."""
        if not self._mqtt_client or not self._mqtt_client.is_connected:
            return
        dev_data = (self._coordinator.data or {}).get(sn)
        if not dev_data:
            return
        model = dev_data.get("device_type", "")
        sub_sn = dev_data.get("sub_sn", "")
        if not model or not sub_sn:
            return
        try:
            self._mqtt_client.send_command(model, sub_sn, PACK_SELECT, pack_num)
            _LOGGER.debug("Pack select: %s → pack %d", sn, pack_num)
        except BluettiMqttError:
            _LOGGER.debug("Failed to send pack select for %s", sn)

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

        mqtt_overlay = self.overlays.setdefault(sn, {})
        mqtt_overlay[switch_key] = new_state
        mqtt_overlay["mqtt_active"] = True

        self._push_mqtt_update()

    def _push_mqtt_update(self) -> None:
        """Merge MQTT overlay into current data and push to HA entities.

        Note: We do NOT update _last_good_data here — that is only set by
        the REST refresh cycle to avoid mixing stale REST + fresh MQTT data
        in the error fallback cache.
        """
        if not self._coordinator.data:
            return

        merged = {}
        for sn, device_data in self._coordinator.data.items():
            merged_device = dict(device_data)
            mqtt_overlay = self.overlays.get(sn)
            if mqtt_overlay:
                merged_device.update(mqtt_overlay)
            merged[sn] = merged_device

        # Notify all entities with merged data (does not affect _last_good_data)
        self._coordinator.async_set_updated_data(merged)
