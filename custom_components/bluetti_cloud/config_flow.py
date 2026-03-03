"""Config flow for Bluetti Cloud integration."""

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api.client import AuthenticationError, BluettiCloudApi, BluettiCloudApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("username"): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL)
        ),
        vol.Required("password"): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


class BluettiCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bluetti Cloud."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._client: BluettiCloudApi | None = None
        self._username: str = ""
        self._password: str = ""
        self._devices: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the credentials step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input["username"]
            self._password = user_input["password"]

            # Check if already configured with this account
            await self.async_set_unique_id(self._username)
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            self._client = BluettiCloudApi(session)

            try:
                await self._client.login(self._username, self._password)
                self._devices = await self._client.get_devices()
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except BluettiCloudApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during login")
                errors["base"] = "unknown"
            else:
                if not self._devices:
                    errors["base"] = "no_devices"
                else:
                    return await self.async_step_devices()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle device selection step."""
        if user_input is not None:
            selected_sns = user_input.get("devices", [])
            device_info = {}
            for dev in self._devices:
                sn = dev.get("sn", "")
                if sn in selected_sns:
                    device_info[sn] = {
                        "name": dev.get("name", sn),
                        "model": dev.get("model", "Unknown"),
                    }

            return self.async_create_entry(
                title=f"Bluetti ({self._username})",
                data={
                    "username": self._username,
                    "password": self._password,
                    "devices": selected_sns,
                    "device_info": device_info,
                },
            )

        # Build device options for multi-select with checkboxes
        options = []
        all_sns = []
        for dev in self._devices:
            sn = dev.get("sn", "")
            name = dev.get("name", sn)
            model = dev.get("model", "")
            session_state = dev.get("sessionState", "Offline")
            online = session_state if session_state else "Offline"
            options.append(
                SelectOptionDict(value=sn, label=f"{name} ({model}) - {online}")
            )
            all_sns.append(sn)

        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(
                {
                    vol.Required("devices", default=all_sns): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )
