"""MQTT client for Bluetti device control and telemetry via cloud.

Connects to the Bluetti IoT MQTT broker using mTLS (P12 client certificates)
and server-time TOTP authentication.

- Publishes Modbus RTU commands to SUB/{model}/{subSn} (device control)
- Subscribes to PUB/{model}/{subSn} for real-time telemetry (homeData frames)

The connection flow:
1. Get server UTC time from API (critical — TOTP uses server time, not local)
2. Download P12 client certificate from API (requires TOTP + AES signature chain)
3. Extract PEM cert/key from P12 using openssl
4. Connect to MQTT broker with mTLS + TOTP password
5. Subscribe to telemetry topics and publish commands
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import ssl
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from typing import Any

import aiohttp
import paho.mqtt.client as mqtt

from .modbus import build_mqtt_payload, build_read_mqtt_payload, parse_mqtt_payload
from .totp import generate_totp
from ..const import APP_ID, GW_PRIMARY_URL, GW_URL

_LOGGER = logging.getLogger(__name__)

MQTT_BROKER = "iot.bluettipower.com"
MQTT_PORT = 18760
MQTT_KEEPALIVE = 20
MQTT_CONNECT_TIMEOUT = 15

# AES-ECB helpers for cert password exchange
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


class BluettiMqttError(Exception):
    """Error communicating with Bluetti MQTT broker."""


def _aes_ecb_decrypt(data: bytes, password: str) -> str:
    cipher = AES.new(password.encode("utf-8"), AES.MODE_ECB)
    return unpad(cipher.decrypt(data), 16).decode("utf-8")


def _aes_ecb_encrypt(plaintext: str, password: str) -> str:
    cipher = AES.new(password.encode("utf-8"), AES.MODE_ECB)
    return cipher.encrypt(pad(plaintext.encode("utf-8"), 16)).hex()


def _get_request_sign(sid: str, app_ver: str, url: str, utc_time: int) -> str:
    params = {
        "currentUtcTime": format(utc_time, "x"),
        "url": url,
        "x-app-key": APP_ID,
        "x-app-ver": app_ver,
        "x-os": "android",
        "x-sid": sid,
    }
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.md5(query.encode("utf-8")).hexdigest().upper()


# Type alias for the telemetry callback:
# (topic: str, parsed_data: dict[str, Any]) -> None
TelemetryCallback = Callable[[str, dict[str, Any]], None]


class BluettiMqttClient:
    """MQTT client for Bluetti device control and telemetry.

    Requires an active aiohttp session and API token for certificate
    download and TOTP generation. Optionally accepts a telemetry callback
    that is invoked (thread-safely) when telemetry frames arrive.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str,
        loop: asyncio.AbstractEventLoop | None = None,
        on_telemetry: TelemetryCallback | None = None,
    ) -> None:
        self._session = session
        self._token = token
        self._loop = loop
        self._on_telemetry = on_telemetry
        self._client: mqtt.Client | None = None
        self._connected = False
        self._connect_error: str | None = None
        self._pem_cert: str | None = None
        self._pem_key: str | None = None
        # Topics to (re-)subscribe on connect
        self._subscriptions: set[str] = set()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_telemetry_callback(self, callback: TelemetryCallback | None) -> None:
        """Set or clear the telemetry callback."""
        self._on_telemetry = callback

    async def _get_server_time(self, headers: dict) -> tuple[int | None, str | None]:
        """Fetch UTC time from server (milliseconds)."""
        for gw in [GW_URL, GW_PRIMARY_URL]:
            try:
                async with self._session.get(
                    f"{gw}/api/midppkic/cert/app/v2/now/utc-time",
                    headers=headers,
                ) as resp:
                    result = await resp.json()
                    d = result.get("data", "")
                    t = int(d) if isinstance(d, str) and d.isdigit() else (
                        int(d) if isinstance(d, (int, float)) else None
                    )
                    sig = resp.headers.get("X-Signature")
                    if t:
                        return t, sig
            except Exception:
                continue
        return None, None

    async def _download_certificates(self) -> None:
        """Download P12 certificate and extract PEM files."""
        if not HAS_CRYPTO:
            raise BluettiMqttError("pycryptodome is required for MQTT control")

        parts = self._token.split(".")
        sid = parts[1]
        app_ver = "3.0.6"
        device_id = hashlib.md5(b"bluetti-ha").hexdigest()

        headers = {
            "Content-type": "application/json;charset=utf-8",
            "x-app-key": APP_ID,
            "x-os": "android",
            "x-os-ver": "31332E30",
            "x-app-ver": app_ver,
            "x-device-id": device_id,
            "Accept-Language": "en-US",
            "Authorization": self._token,
        }

        # Get server time + signature
        utc_time, signature = await self._get_server_time(headers)
        if not utc_time or not signature:
            raise BluettiMqttError("Cannot get server time for certificate download")

        # Get user ID
        async with self._session.get(
            f"{GW_URL}/api/bluuc/uc/v1/basic/get", headers=headers
        ) as resp:
            user_id = (await resp.json()).get("data", {}).get("uid")

        # Derive cert password from signature
        req_sign = _get_request_sign(
            sid, app_ver, "/api/midppkic/cert/app/v2/now/utc-time", utc_time
        )
        cert_pw = _aes_ecb_decrypt(bytes.fromhex(signature), req_sign)

        # Generate TOTP for PFX download
        totp_pfx = generate_totp(user_id, device_id, utc_time)
        pfx_sign = _get_request_sign(
            sid, app_ver, "/api/midppkic/cert/app/v1/pfx", int(totp_pfx)
        )
        pfx_headers = dict(headers)
        pfx_headers["x-app-resource"] = _aes_ecb_encrypt(cert_pw, pfx_sign)

        # Download P12
        pfx_data = None
        for gw in [GW_PRIMARY_URL, GW_URL]:
            try:
                async with self._session.post(
                    f"{gw}/api/midppkic/cert/app/v1/pfx",
                    headers=pfx_headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    data = await resp.read()
                    try:
                        if data.decode("utf-8").startswith("{"):
                            continue
                    except (UnicodeDecodeError, ValueError):
                        pass
                    pfx_data = data
                    break
            except Exception:
                continue

        if not pfx_data:
            raise BluettiMqttError("Failed to download P12 certificate")

        # Write P12 and extract PEM
        pfx_path = os.path.join(tempfile.gettempdir(), "bluetti_ha_cert.p12")
        self._pem_cert = os.path.join(tempfile.gettempdir(), "bluetti_ha_cert.pem")
        self._pem_key = os.path.join(tempfile.gettempdir(), "bluetti_ha_key.pem")

        with open(pfx_path, "wb") as f:
            f.write(pfx_data)

        for legacy in [True, False]:
            extras = ["-legacy"] if legacy else []
            r1 = subprocess.run(
                ["openssl", "pkcs12", "-in", pfx_path, "-out", self._pem_cert,
                 "-clcerts", "-nokeys", "-passin", f"pass:{cert_pw}"] + extras,
                capture_output=True,
            )
            r2 = subprocess.run(
                ["openssl", "pkcs12", "-in", pfx_path, "-out", self._pem_key,
                 "-nocerts", "-nodes", "-passin", f"pass:{cert_pw}"] + extras,
                capture_output=True,
            )
            if r1.returncode == 0 and r2.returncode == 0:
                _LOGGER.debug("P12 certificate extracted successfully")
                break
        else:
            raise BluettiMqttError("Failed to extract PEM from P12 certificate")

        # Clean up P12
        try:
            os.unlink(pfx_path)
        except OSError:
            pass

    async def async_prepare(self) -> dict:
        """Async phase: download certificates + get TOTP (uses aiohttp on HA loop).

        Returns a dict with all data needed for the blocking connect phase.
        Must be called from the HA event loop (where the aiohttp session lives).
        """
        # Download certificates if needed
        if not self._pem_cert or not os.path.exists(self._pem_cert):
            await self._download_certificates()

        parts = self._token.split(".")
        app_ver = "3.0.6"
        device_id = hashlib.md5(b"bluetti-ha").hexdigest()

        headers = {
            "Content-type": "application/json;charset=utf-8",
            "x-app-key": APP_ID,
            "x-os": "android",
            "x-os-ver": "31332E30",
            "x-app-ver": app_ver,
            "x-device-id": device_id,
            "Accept-Language": "en-US",
            "Authorization": self._token,
        }

        # Get fresh server time for TOTP
        utc_time, _ = await self._get_server_time(headers)
        if not utc_time:
            raise BluettiMqttError("Cannot get server time for MQTT TOTP")

        mqtt_user = f"tid:{parts[1]}"
        mqtt_pass = generate_totp(parts[1], parts[0], utc_time)
        client_id = hashlib.md5(
            f"BLUETTI_HA&{uuid.uuid4()}&{int(time.time() * 1000)}".encode()
        ).hexdigest()

        return {
            "pem_cert": self._pem_cert,
            "pem_key": self._pem_key,
            "mqtt_user": mqtt_user,
            "mqtt_pass": mqtt_pass,
            "client_id": client_id,
        }

    def connect_blocking(self, prep: dict) -> None:
        """Blocking phase: TCP+TLS connect to MQTT broker (runs in executor thread).

        Takes the preparation dict from async_prepare(). This method uses
        time.sleep() for polling and must NOT be called from the event loop.
        """
        # TLS context with client certificate
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        except Exception:
            pass
        ctx.load_cert_chain(prep["pem_cert"], prep["pem_key"])

        self._connected = False
        self._connect_error = None

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=prep["client_id"],
            protocol=mqtt.MQTTv311,
        )
        self._client.username_pw_set(prep["mqtt_user"], prep["mqtt_pass"])
        self._client.tls_set_context(ctx)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        _LOGGER.debug("Connecting to MQTT broker %s:%d", MQTT_BROKER, MQTT_PORT)

        try:
            self._client.connect(MQTT_BROKER, MQTT_PORT, keepalive=MQTT_KEEPALIVE)
            self._client.loop_start()
        except Exception as err:
            raise BluettiMqttError(f"MQTT connection failed: {err}") from err

        # Poll for connection (blocking — safe in executor thread)
        deadline = time.time() + MQTT_CONNECT_TIMEOUT
        while not self._connected and not self._connect_error and time.time() < deadline:
            time.sleep(0.2)

        if not self._connected:
            self._client.loop_stop()
            raise BluettiMqttError(
                f"MQTT connection failed: {self._connect_error or 'timeout'}"
            )

        _LOGGER.info("MQTT connected to %s", MQTT_BROKER)

    def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
            self._connected = False

    def cleanup_pem_files(self) -> None:
        """Remove temporary PEM files."""
        for path in (self._pem_cert, self._pem_key):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        self._pem_cert = None
        self._pem_key = None

    def subscribe_telemetry(self, model: str, sub_sn: str) -> None:
        """Subscribe to a device's telemetry topic.

        Safe to call before or after connect — subscriptions are tracked
        and (re-)applied on every connect/reconnect.
        """
        topic = f"PUB/{model}/{sub_sn}"
        self._subscriptions.add(topic)
        if self._client and self._connected:
            self._client.subscribe(topic, qos=1)
            _LOGGER.debug("Subscribed to telemetry topic: %s", topic)

    def send_command(
        self, model: str, sub_sn: str, register: int, value: int
    ) -> None:
        """Send a Modbus write command to a device via MQTT."""
        if not self._client or not self._connected:
            raise BluettiMqttError("Not connected to MQTT broker")

        topic = f"SUB/{model}/{sub_sn}"
        payload = build_mqtt_payload(register, value)

        _LOGGER.debug(
            "MQTT publish %s: reg=%d val=%d payload=%s",
            topic, register, value, payload.hex(),
        )

        result = self._client.publish(topic, payload, qos=1)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise BluettiMqttError(
                f"MQTT publish failed: {mqtt.error_string(result.rc)}"
            )

    def send_read_request(
        self, model: str, sub_sn: str, register: int, count: int,
        slave_addr: int = 1,
    ) -> None:
        """Send a Modbus FC=03 read request to a device via MQTT.

        The device will respond on the PUB topic with the requested register data.
        """
        if not self._client or not self._connected:
            raise BluettiMqttError("Not connected to MQTT broker")

        topic = f"SUB/{model}/{sub_sn}"
        payload = build_read_mqtt_payload(register, count, slave_addr)

        _LOGGER.debug(
            "MQTT read request %s: reg=%d count=%d slave=%d payload=%s",
            topic, register, count, slave_addr, payload.hex(),
        )

        result = self._client.publish(topic, payload, qos=1)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise BluettiMqttError(
                f"MQTT publish failed: {mqtt.error_string(result.rc)}"
            )

    # -- paho-mqtt callbacks (run in paho's network thread) --

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            _LOGGER.debug("MQTT connected")
            self._connected = True
            # (Re-)subscribe to all tracked topics on connect/reconnect
            for topic in self._subscriptions:
                client.subscribe(topic, qos=1)
                _LOGGER.debug("(Re-)subscribed to %s", topic)
        else:
            _LOGGER.error("MQTT connect failed: %s", reason_code)
            self._connect_error = str(reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        _LOGGER.debug("MQTT disconnected: %s", reason_code)
        self._connected = False

    def _on_message(self, client, userdata, message):
        """Handle incoming MQTT messages (telemetry frames).

        This runs in paho's network thread. We parse the Modbus frame here
        and dispatch to the telemetry callback via the event loop (thread-safe).
        """
        parsed = parse_mqtt_payload(message.payload)
        if not parsed:
            _LOGGER.debug(
                "Unparseable MQTT message on %s: %s",
                message.topic, message.payload.hex() if message.payload else "(empty)",
            )
            return

        _LOGGER.debug(
            "MQTT telemetry on %s: FC=%d len=%d",
            message.topic, parsed["function_code"],
            len(parsed.get("data", b"")),
        )

        callback = self._on_telemetry
        if callback is None:
            return

        # Dispatch to HA event loop thread-safely (never call directly from paho thread)
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(callback, message.topic, parsed)
        else:
            _LOGGER.warning("Cannot dispatch telemetry — event loop not available")
