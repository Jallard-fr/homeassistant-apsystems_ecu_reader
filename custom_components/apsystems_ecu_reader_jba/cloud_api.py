"""cloud_api.py - Client for the APsystems OpenAPI (EMA cloud)."""

import asyncio
import base64
import hashlib
import hmac
import logging
import time
import uuid

import aiohttp

from .const import CLOUD_BASE_URL, CLOUD_METER_FIELDS, CLOUD_PERIODS

_LOGGER = logging.getLogger(__name__)

RESPONSE_CODES = {
    1000: "Data exception",
    1001: "No data",
    2000: "Application account exception",
    2001: "Invalid application account",
    2002: "The application account is not authorized",
    2003: "Application account authorization expires",
    2004: "The application account has no permission",
    2005: "The access limit of the application account was exceeded",
    4000: "Request parameter exception",
    4001: "Invalid request parameter",
    5000: "Internal server exception",
    6000: "Communication exception",
    7000: "Server access restriction exception",
    7001: "Server access limit exceeded",
    7002: "Too many requests, please request later",
    7003: "The system is busy, please request later",
}


class APsystemsCloudError(Exception):
    """Exception for errors returned by the APsystems OpenAPI."""


class APsystemsCloudAPI:
    """Query the APsystems OpenAPI for meter summary energy."""

    def __init__(self, app_id, app_secret, sid, timeout=15):
        self.app_id = app_id
        self.app_secret = app_secret
        self.sid = sid
        self.timeout = timeout
        self.eid = None
        # Number of HTTP requests sent, the APsystems quota counts every call
        self.calls = 0

    def _headers(self, path, method="GET"):
        """Build the signed headers (HmacSHA256) for a request."""
        timestamp = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        signature_method = "HmacSHA256"
        # RequestPath is the last segment of the path
        request_path = path.rstrip("/").rsplit("/", 1)[-1]
        string_to_sign = "/".join(
            [timestamp, nonce, self.app_id, request_path, method, signature_method]
        )
        signature = base64.b64encode(
            hmac.new(
                self.app_secret.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        return {
            "X-CA-AppId": self.app_id,
            "X-CA-Timestamp": timestamp,
            "X-CA-Nonce": nonce,
            "X-CA-Signature-Method": signature_method,
            "X-CA-Signature": signature,
        }

    async def _get(self, path):
        """Perform a signed GET request and return the 'data' part."""
        url = f"{CLOUD_BASE_URL}{path}"
        self.calls += 1
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=self._headers(path), timeout=self.timeout
                ) as response:
                    if response.status != 200:
                        raise APsystemsCloudError(
                            f"HTTP status {response.status} for {path}"
                        )
                    result = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise APsystemsCloudError(f"request {path} failed: {err}") from err

        _LOGGER.debug("APsystems OpenAPI response for %s: %s", path, result)
        code = result.get("code") if isinstance(result, dict) else None
        if code != 0:
            raise APsystemsCloudError(
                f"code {code} ({RESPONSE_CODES.get(code, 'Unknown error')}) for {path}"
            )
        return result.get("data")

    async def get_meter_eid(self):
        """Discover the meter ECU id (eid) of the system."""
        meters = await self._get(f"/user/api/v2/systems/meters/{self.sid}")
        if not meters:
            raise APsystemsCloudError(f"no meter found for system {self.sid}")
        if len(meters) > 1:
            _LOGGER.warning(
                "System %s has %s meters, using the first one: %s",
                self.sid,
                len(meters),
                meters[0],
            )
        self.eid = meters[0]
        return self.eid

    async def get_meter_summary(self):
        """Return the meter summary energy mapped to sensor fields."""
        if not self.eid:
            await self.get_meter_eid()
        data = await self._get(
            f"/user/api/v2/systems/{self.sid}/devices/meter/summary/{self.eid}"
        )
        if not isinstance(data, dict):
            raise APsystemsCloudError("unexpected meter summary format")

        mapped_data = {}
        for period in CLOUD_PERIODS:
            for field in CLOUD_METER_FIELDS:
                value = (data.get(period) or {}).get(field)
                try:
                    mapped_data[f"cloud_{period}_{field}"] = round(float(value), 3)
                except (TypeError, ValueError):
                    mapped_data[f"cloud_{period}_{field}"] = None
        return mapped_data
