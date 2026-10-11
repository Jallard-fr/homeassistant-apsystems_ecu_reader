"""Config flow for APsystems ECU Reader."""

import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import (
    DOMAIN,
    KEYS,
    CLOUD_KEYS,
    DEFAULT_CLOUD_INTERVAL,
    MIN_CLOUD_INTERVAL,
)
from .ecu_api import APsystemsSocket, APsystemsInvalidData
from .cloud_api import APsystemsCloudAPI, APsystemsCloudError


_LOGGER = logging.getLogger(__name__)

"""Set defaults for the configuration."""
DEFAULTS = {
    KEYS[0]: "",  # ecu_host
    KEYS[1]: 300,  # scan_interval
    KEYS[2]: 5,  # port_retries
    KEYS[3]: 3,  # cache_reboot
    KEYS[4]: True,  # show_graphs
    KEYS[5]: "ECU-WIFI_local",  # wifi_ssid
    KEYS[6]: "default",  # wifi_password
    KEYS[7]: "",  # cloud_app_id
    KEYS[8]: "",  # cloud_app_secret
    KEYS[9]: "",  # cloud_sid
    KEYS[10]: DEFAULT_CLOUD_INTERVAL,  # cloud_interval (minutes)
}


def build_schema(values):
    """Build the form schema, prefilled with the given values."""

    def default(key):
        return values.get(key, DEFAULTS[key])

    return vol.Schema(
        {
            vol.Required(KEYS[0], default=default(KEYS[0])): str,
            vol.Required(KEYS[1], default=default(KEYS[1])): int,
            vol.Required(KEYS[2], default=default(KEYS[2])): vol.All(
                int, vol.Range(min=1, max=10)
            ),
            vol.Required(KEYS[3], default=default(KEYS[3])): vol.All(
                int, vol.Range(min=3, max=5)
            ),
            vol.Optional(KEYS[4], default=default(KEYS[4])): bool,
            vol.Optional(KEYS[5], default=default(KEYS[5])): str,
            vol.Optional(KEYS[6], default=default(KEYS[6])): str,
            vol.Optional(KEYS[7], default=default(KEYS[7])): str,
            vol.Optional(KEYS[8], default=default(KEYS[8])): str,
            vol.Optional(KEYS[9], default=default(KEYS[9])): str,
            vol.Optional(KEYS[10], default=default(KEYS[10])): vol.All(
                int, vol.Range(min=MIN_CLOUD_INTERVAL, max=1440)
            ),
        }
    )


@config_entries.HANDLERS.register(DOMAIN)
class FlowHandler(config_entries.ConfigFlow):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        placeholders = {"error": ""}

        if user_input:
            cloud_error = await test_cloud_connection(user_input)
            if cloud_error:
                field, errors[field], placeholders["error"] = cloud_error
            elif ecu_id := await test_ecu_connection(user_input):
                await self.async_set_unique_id(ecu_id)
                self._abort_if_unique_id_configured()
                # Use the ECU-ID in the title to ensure uniqueness
                return self.async_create_entry(
                    title=f"APsystems ECU {ecu_id}", data=user_input
                )
            else:
                errors["ecu_host"] = "no_ecu_found"

        # Show the form, keeping what the user typed when there is an error
        return self.async_show_form(
            step_id="user",
            data_schema=build_schema(user_input or {}),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow changes."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self.entry = entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}
        placeholders = {"error": ""}

        if user_input:
            cloud_error = await test_cloud_connection(user_input)
            # Only test the ECU again when its address changed, the ECU is
            # already being polled and a second query often fails.
            host_changed = user_input[KEYS[0]] != self.entry.data.get(KEYS[0])
            if cloud_error:
                field, errors[field], placeholders["error"] = cloud_error
            elif not host_changed or await test_ecu_connection(user_input):
                self.hass.config_entries.async_update_entry(
                    self.entry, data={**self.entry.data, **user_input}
                )
                return self.async_create_entry(title="APsystems", data={})
            else:
                errors["ecu_host"] = "no_ecu_found"

        # Show the form, keeping what the user typed when there is an error
        return self.async_show_form(
            step_id="init",
            data_schema=build_schema(user_input or self.entry.data),
            errors=errors,
            description_placeholders=placeholders,
        )


async def test_ecu_connection(input_data):
    """Test the connection to the ECU and return the ECU ID if successful."""
    try:
        ecu = APsystemsSocket(input_data.get(KEYS[0]))
        retries = input_data.get(KEYS[2], 2)
        test_query = await ecu.get_update(retries, True)
        return test_query.get("ecu_id", None)
    # collector of APsystemsInvalidData exceptions
    except APsystemsInvalidData as err:
        _LOGGER.warning(
            "APsystems invalid data exception for ECU %s: %s", ecu.ecu_id, err
        )
        return None


async def test_cloud_connection(input_data):
    """Validate the optional OpenAPI settings.

    Return (field, error key, detail) on failure, None when valid or unused.
    This costs one OpenAPI call when the settings are filled in.
    """
    for key in CLOUD_KEYS:
        input_data[key] = input_data.get(key, "").strip()
    values = [input_data[key] for key in CLOUD_KEYS]
    if not any(values):
        return None
    if not all(values):
        missing = next(key for key in CLOUD_KEYS if not input_data[key])
        return missing, "cloud_incomplete", ""
    try:
        await APsystemsCloudAPI(*values).get_meter_eid()
    except APsystemsCloudError as err:
        _LOGGER.warning("APsystems OpenAPI test failed: %s", err)
        return KEYS[7], "cloud_connection_failed", str(err)
    return None
