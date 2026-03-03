"""Async API client for Bluetti Cloud (mobile app API)."""

import logging
import time
from typing import Any

import aiohttp

from .crypto import encrypt_password, hash_password
from ..const import APP_ID, GW_PRIMARY_URL, GW_URL

_LOGGER = logging.getLogger(__name__)


class BluettiCloudApiError(Exception):
    """Base exception for API errors."""


class AuthenticationError(BluettiCloudApiError):
    """Raised when authentication fails."""


class BluettiCloudApi:
    """Async client for the Bluetti mobile app cloud API."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._token: str | None = None
        self._refresh: str | None = None
        self._token_expiry: float = 0
        self._username: str | None = None
        self._password: str | None = None

    @property
    def is_authenticated(self) -> bool:
        return self._token is not None and time.time() < self._token_expiry

    def _headers(self) -> dict[str, str]:
        headers = {
            "x-app-key": APP_ID,
            "x-os": "android",
            "Accept-Language": "en-US",
        }
        if self._token:
            headers["Authorization"] = self._token
        return headers

    async def login(self, username: str, password: str) -> None:
        """Authenticate with Bluetti Cloud.

        Args:
            username: Bluetti account email.
            password: Plaintext password (will be transformed).

        Raises:
            AuthenticationError: If login fails.
        """
        self._username = username
        self._password = password

        data = {
            "username": username,
            "password": hash_password(password),
            "passOpen": encrypt_password(password),
            "encryptedpwd": "",
            "authType": "",
            "phoneCountry": "",
            "verifyCode": "",
            "country": "",
        }

        headers = {
            "x-app-key": APP_ID,
            "x-os": "android",
            "Accept-Language": "en-US",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            async with self._session.post(
                f"{GW_URL}/accessToken",
                data=data,
                headers=headers,
            ) as resp:
                result = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise BluettiCloudApiError(f"Connection failed: {err}") from err

        if result.get("data") and result["data"].get("token"):
            self._token = result["data"]["token"]
            self._refresh = result["data"].get("refresh")
            ttl = int(result["data"].get("ttl", 2678400))
            self._token_expiry = time.time() + ttl
            _LOGGER.debug("Login successful, token expires in %d seconds", ttl)
        else:
            msg = result.get("message", "Unknown error")
            raise AuthenticationError(f"Login failed: {msg}")

    async def _ensure_authenticated(self) -> None:
        """Re-login if token has expired."""
        if not self.is_authenticated:
            if self._username and self._password:
                await self.login(self._username, self._password)
            else:
                raise AuthenticationError("Not authenticated and no credentials stored")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        base_url: str | None = None,
        json_data: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated API request.

        Uses gwpry for /api/bluiotdata/ endpoints, gw for everything else.
        """
        await self._ensure_authenticated()

        if base_url is None:
            base_url = GW_PRIMARY_URL if "/bluiotdata/" in path else GW_URL

        url = f"{base_url}{path}"
        headers = self._headers()
        if json_data is not None:
            headers["Content-Type"] = "application/json;charset=utf-8"

        try:
            async with self._session.request(
                method,
                url,
                json=json_data,
                params=params,
                headers=headers,
            ) as resp:
                result = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise BluettiCloudApiError(f"Request failed: {err}") from err

        msg_code = result.get("msgCode", result.get("code", -1))
        if msg_code == 805:
            # Token expired — re-authenticate and retry once
            _LOGGER.debug("Token expired (805), re-authenticating")
            await self.login(self._username, self._password)
            headers = self._headers()
            if json_data is not None:
                headers["Content-Type"] = "application/json;charset=utf-8"
            async with self._session.request(
                method,
                url,
                json=json_data,
                params=params,
                headers=headers,
            ) as resp:
                result = await resp.json()

        return result

    async def get_devices(self) -> list[dict[str, Any]]:
        """Fetch all devices with embedded telemetry.

        Returns list of device dicts from the homeDevices endpoint.
        """
        result = await self._request(
            "GET",
            "/api/blusmartprod/device/group/v1/homeDevices",
        )
        data = result.get("data", {})
        # homeDevices returns groups; flatten device lists
        devices = []
        if isinstance(data, list):
            for group in data:
                device_list = group.get("deviceList", [])
                devices.extend(device_list)
        elif isinstance(data, dict):
            device_list = data.get("deviceList", [])
            devices.extend(device_list)
        return devices

    async def get_device_last_alive(self, device_sn: str) -> dict[str, Any]:
        """Fetch detailed live telemetry for a device.

        Args:
            device_sn: Device serial number.

        Returns:
            Dict of telemetry data.
        """
        result = await self._request(
            "POST",
            "/api/bluiotdata/realtime/v1/getDeviceLastAlive",
            json_data={"deviceSn": device_sn},
        )
        return result.get("data", {})

    async def control_device(
        self, sn: str, fn_code: str, fn_value: str
    ) -> dict[str, Any]:
        """Send a control command to a device.

        Args:
            sn: Device serial number.
            fn_code: Function code (e.g., 'SetCtrlAcSwitch').
            fn_value: Value to set ('0' or '1').

        Returns:
            API response dict.
        """
        result = await self._request(
            "POST",
            "/api/bluiotdata/ha/v1/fulfillment",
            json_data={"sn": sn, "fnCode": fn_code, "fnValue": fn_value},
        )
        return result
