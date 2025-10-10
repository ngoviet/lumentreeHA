# /config/custom_components/lumentree/config_flow.py
# Final version - Add robustness to _get_api_client

import json
import time
from typing import Any, Dict, Optional
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:
    from .const import (
        DOMAIN, CONF_DEVICE_ID, CONF_DEVICE_SN, CONF_DEVICE_NAME, CONF_HTTP_TOKEN, _LOGGER
    )
    from .api import LumentreeHttpApiClient, AuthException, ApiException
except ImportError:
    _LOGGER = logging.getLogger(__name__)
    _LOGGER.warning("ImportError config_flow.py: Using fallback definitions.")
    DOMAIN = "lumentree"; CONF_DEVICE_ID = "device_id"; CONF_DEVICE_SN = "device_sn"; CONF_DEVICE_NAME = "device_name"; CONF_HTTP_TOKEN = "http_token"
    class LumentreeHttpApiClient:
        def __init__(self, session): pass
        async def authenticate_device(self, device_id): return "fallback_token"
        async def get_device_info(self, dev_id): return {"deviceId": dev_id, "deviceType": "Fallback Model"}
        def set_token(self, token): pass
    class AuthException(Exception): pass
    class ApiException(Exception): pass

class LumentreeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Lumentree (Device ID based auth)."""
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL
    
    def __init__(self) -> None:
        self._device_id_input: Optional[str] = None
        self._http_token: Optional[str] = None
        self._device_sn_from_api: Optional[str] = None
        self._device_name: Optional[str] = None
        self._api_client: Optional[LumentreeHttpApiClient] = None
        self._reauth_entry: Optional[config_entries.ConfigEntry] = None

    # --- SỬA HÀM NÀY ---
    async def _get_api_client(self) -> LumentreeHttpApiClient:
        """Get or create HTTP API client, ensuring it's not None."""
        _LOGGER.debug("Attempting to get API client instance...")
        if self._api_client is None:
            _LOGGER.debug("API client is None, creating new instance.")
            try:
                session = async_get_clientsession(self.hass)
                _LOGGER.debug("aiohttp client session obtained: %s", repr(session))
                if session is None:
                    _LOGGER.error("Failed to get aiohttp client session! (session is None)")
                    raise ApiException("Could not get client session")

                # Create instance in separate try/except
                try:
                    # Log before creating to know session status
                    _LOGGER.debug("Creating LumentreeHttpApiClient with session: %s", getattr(session, 'cookie_jar', 'no-cookie-jar'))
                    self._api_client = LumentreeHttpApiClient(session)
                    _LOGGER.debug("Created new API client instance: %s", type(self._api_client))
                except Exception as create_exc:
                    # Write detailed stacktrace to debug client creation error
                    _LOGGER.exception("Error creating LumentreeHttpApiClient instance: %s", create_exc)
                    raise ApiException("Failed to create API client instance") from create_exc

            except Exception as session_exc:
                # Catch errors from get session or client creation
                _LOGGER.error(f"Failed to initialize API client: {session_exc}")
                # Raise ApiException to report error for next steps
                _LOGGER.debug("Raising ApiException from initialization failure with repr: %s", repr(session_exc))
                raise ApiException(f"API Client Initialization failed: {session_exc}") from session_exc
        else:
            _LOGGER.debug(f"Reusing existing API client instance: {type(self._api_client)}")

        # Check again before setting token and return
        if self._api_client is None:
            # This case should not happen if above logic is correct
            _LOGGER.critical("API client is unexpectedly None after initialization attempt!")
            raise ApiException("API client is None after creation attempt")

        # Assign token if available
        if self._http_token:
            if hasattr(self._api_client, "set_token"):
                try:
                    # Set token and log (hide most of token for security)
                    self._api_client.set_token(self._http_token)
                    masked = (self._http_token[:6] + '...') if len(self._http_token) > 6 else '***'
                    _LOGGER.debug("Set token on API client (masked): %s", masked)
                except Exception as token_exc:
                    _LOGGER.exception("Failed to set token on API client: %s", token_exc)
                    raise ApiException("Failed to set token on API client") from token_exc
            else:
                _LOGGER.warning("API client (or fallback) missing 'set_token' method.")

        return self._api_client
    # --- HẾT PHẦN SỬA ---

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        errors: Dict[str, str] = {}; api: Optional[LumentreeHttpApiClient] = None # Initialize api as None
        if user_input is not None:
            self._device_id_input = user_input[CONF_DEVICE_ID].strip()
            try:
                # Get API client, this function will now raise ApiException if failed
                api = await self._get_api_client()
                _LOGGER.info("Authenticating with Device ID: %s", self._device_id_input)
                _LOGGER.debug("Using API client instance: %s", type(api))
                token = await api.authenticate_device(self._device_id_input) # Call method on confirmed non-None instance
                self._http_token = token
                masked_token = (token[:6] + '...') if token and len(token) > 6 else '***'
                _LOGGER.info("Auth success for %s (token masked: %s)", self._device_id_input, masked_token)
                return await self.async_step_confirm_device()
            except AuthException as exc:
                _LOGGER.warning(f"Auth failed {self._device_id_input}: {exc}")
                errors["base"] = "invalid_auth"
            except ApiException as exc:
                _LOGGER.error(f"API conn/init error auth {self._device_id_input}: {exc}")
                errors["base"] = "cannot_connect"
            except Exception as exc:
                _LOGGER.exception(f"Unexpected auth error {self._device_id_input}: {exc}")
                errors["base"] = "unknown" # Catch other errors if any

        schema = vol.Schema({vol.Required(CONF_DEVICE_ID, default=self._device_id_input or ""): str})
        # If there are errors, show user form again
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


    async def async_step_confirm_device(self, user_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        errors: Dict[str, str] = {}; api: Optional[LumentreeHttpApiClient] = None
        if not self._http_token: _LOGGER.error("Token missing"); return self.async_abort(reason="token_missing")

        try: # Add try around getting api client at this step
            api = await self._get_api_client() # Get client (already has token set inside)
        except ApiException as exc: # Catch error if cannot get client at confirm step
            _LOGGER.exception("Failed to get API client in confirm step: %s", exc)
            errors["base"] = "cannot_connect"
            # Show user form again
            return self.async_show_form(step_id="confirm_device", description_placeholders={"device_name": "Error", "device_sn": "Error"}, errors=errors)

        if user_input is None:
            if not self._device_id_input: _LOGGER.error("Device ID missing"); return self.async_abort(reason="cannot_connect")
            try:
                _LOGGER.info("Fetching device info for %s via API...", self._device_id_input)
                device_info_api = await api.get_device_info(self._device_id_input) # api is definitely not None here
                _LOGGER.debug("Device info raw response: %s", device_info_api)

                if isinstance(device_info_api, dict) and "_error" in device_info_api:
                    api_error = device_info_api["_error"]
                    _LOGGER.error("API error when getting device info: %s", api_error)
                    errors["base"] = "invalid_auth" if "Auth" in api_error else "cannot_connect_deviceinfo"
                    return self.async_show_form(step_id="confirm_device", description_placeholders={"device_name": "Err", "device_sn": "Err"}, errors=errors)

                self._device_sn_from_api = device_info_api.get("deviceId") if isinstance(device_info_api, dict) else None
                if not self._device_sn_from_api:
                    _LOGGER.warning("deviceId not found for %s. Using input ID.", self._device_id_input)
                    self._device_sn_from_api = self._device_id_input
                elif self._device_sn_from_api != self._device_id_input:
                    _LOGGER.warning("API deviceId '%s' differs from input '%s'. Using API ID.", self._device_sn_from_api, self._device_id_input)

                self._device_name = (device_info_api.get("remarkName") if isinstance(device_info_api, dict) else None) or (device_info_api.get("deviceType") if isinstance(device_info_api, dict) else None) or f"Lumentree {self._device_sn_from_api}"
                _LOGGER.info("Device Info: ID/SN='%s', Name='%s', Type='%s'", self._device_sn_from_api, self._device_name, (device_info_api.get('deviceType') if isinstance(device_info_api, dict) else None))

                await self.async_set_unique_id(self._device_sn_from_api)
                updates = {CONF_DEVICE_NAME: self._device_name, CONF_DEVICE_ID: self._device_id_input, CONF_HTTP_TOKEN: self._http_token}
                if self._reauth_entry:
                    pass
                else:
                    self._abort_if_unique_id_configured(updates=updates)

                return self.async_show_form(step_id="confirm_device", description_placeholders={CONF_DEVICE_NAME: self._device_name, CONF_DEVICE_SN: self._device_sn_from_api}, errors={})
            except AuthException as exc:
                _LOGGER.error(f"Auth error get info {self._device_id_input}: {exc}")
                errors["base"] = "invalid_auth"
            except ApiException as exc:
                _LOGGER.error(f"API error get info {self._device_id_input}: {exc}")
                errors["base"] = "cannot_connect_deviceinfo"
            except Exception:
                _LOGGER.exception(f"Unexpected confirm error {self._device_id_input}")
                errors["base"] = "unknown"
            return self.async_show_form(step_id="confirm_device", description_placeholders={"device_name":"Err", "device_sn":"Err"}, errors=errors)

        config_data = {CONF_DEVICE_ID: self._device_id_input, CONF_DEVICE_SN: self._device_sn_from_api, CONF_DEVICE_NAME: self._device_name, CONF_HTTP_TOKEN: self._http_token}
        if self._reauth_entry:
            _LOGGER.info(f"Updating entry {self._reauth_entry.entry_id} for {self._device_sn_from_api} reauth."); self.hass.config_entries.async_update_entry(self._reauth_entry, data=config_data)
            await self.hass.config_entries.async_reload(self._reauth_entry.entry_id); return self.async_abort(reason="reauth_successful")
        _LOGGER.info(f"Creating new entry for SN/ID: {self._device_sn_from_api}"); return self.async_create_entry(title=self._device_name, data=config_data)

    async def async_step_reauth(self, user_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        _LOGGER.info("Reauth flow started."); self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if not self._reauth_entry: return self.async_abort(reason="unknown_entry")
        self._device_id_input = self._reauth_entry.data.get(CONF_DEVICE_ID)
        if not self._device_id_input: _LOGGER.error(f"Cannot reauth {self._reauth_entry.entry_id}: Device ID missing."); return self.async_abort(reason="missing_device_id")
        self._http_token = None; self._api_client = None; return await self.async_step_user(user_input={CONF_DEVICE_ID: self._device_id_input})