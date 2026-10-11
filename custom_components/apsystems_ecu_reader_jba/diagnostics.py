"""Diagnostics for the APsystems ECU Reader.

Downloading the diagnostics queries the ECU on demand and returns the raw
answers of every known local command, including the ones the integration does
not use (yet), so undecoded information can be found.
"""

import asyncio
import json
import logging
import re

import aiohttp

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.util import dt as dt_util

from .const import DOMAIN, PORT
from .ecu_api import GLOBAL_ECU_LOCK

_LOGGER = logging.getLogger(__name__)

TO_REDACT = {"wifi_password", "cloud_app_secret", "cloud_app_id"}

# Read-only pages of the local web interface (ECU-C / ECU-R-Pro).
# Never add "set_..." endpoints here, they change the ECU configuration.
WEB_PATHS = [
    "index.php/home",
    "index.php/realtimedata",
    "index.php/realtimedata/old_power_graph",
    "index.php/realtimedata/power_graph",
    "index.php/realtimedata/old_energy_graph",
    "index.php/realtimedata/energy_graph",
    "index.php/meter",
    "index.php/meter/old_meter_power_graph",
    "index.php/meter/meter_power_graph",
    "index.php/meter/old_meter_energy_graph",
    "index.php/meter/meter_energy_graph",
]

MAX_TEXT = 20000


def socket_commands(ecu_id):
    """Return the known socket commands (name, payload)."""
    today = dt_util.now().strftime("%Y%m%d")
    return [
        # Used by the integration
        ("ecu_info", "APS1100160001END\n"),
        ("inverter_realtime", f"APS1100280002{ecu_id}END\n"),
        ("inverter_signal", f"APS1100280030{ecu_id}END\n"),
        # Not used by the integration, known from other open source clients
        ("inverter_signal_alt_0003", f"APS1100280003{ecu_id}END\n"),
        ("power_of_today", f"APS1100360003{ecu_id}END{today}\n"),
        ("energy_of_week", f"APS1100300004{ecu_id}END00\n"),
        ("energy_of_month", f"APS1100300004{ecu_id}END01\n"),
        ("energy_of_year", f"APS1100300004{ecu_id}END02\n"),
    ]


def describe_frame(data):
    """Describe a raw ECU answer: header, declared vs received length, trailer."""
    info = {
        "received_length": len(data),
        "hex": data.hex(),
        "ascii": "".join(chr(b) if 32 <= b < 127 else "." for b in data),
    }
    if len(data) >= 13 and data[:3] == b"APS":
        try:
            info["declared_length"] = int(data[5:9].decode())
        except ValueError:
            info["declared_length"] = None
        info["command"] = data[9:13].decode(errors="replace")
        info["ends_with_END"] = data.endswith(b"END\n") or data.endswith(b"END")
        info["truncated_by_1024_byte_read"] = len(data) > 1024
    return info


def map_ecu_info(data):
    """Map the bytes of the ecu_info answer to known fields and unknown gaps."""

    def num(start, length):
        return int.from_bytes(data[start : start + length], "big")

    def text(start, length):
        return data[start : start + length].decode(errors="replace")

    fields = []
    try:
        fields += [
            (0, 13, "header", text(0, 13)),
            (13, 12, "ecu_id", text(13, 12)),
            (25, 2, "frame_type", text(25, 2)),
            (27, 4, "lifetime_energy_kwh", num(27, 4) / 10),
            (31, 4, "current_power_w", num(31, 4)),
            (35, 4, "today_energy_kwh", num(35, 4) / 100),
        ]
        if text(25, 2) == "01":
            vsl = int(text(52, 3))
            tsl = int(text(55 + vsl, 3))
            fields += [
                (46, 2, "qty_of_inverters", num(46, 2)),
                (48, 2, "qty_of_online_inverters", num(48, 2)),
                (52, 3, "firmware_length", vsl),
                (55, vsl, "firmware", text(55, vsl)),
                (55 + vsl, 3, "timezone_length", tsl),
                (58 + vsl, tsl, "timezone", text(58 + vsl, tsl)),
            ]
        elif text(25, 2) == "02":
            vsl = int(text(49, 3))
            fields += [
                (39, 2, "qty_of_inverters", num(39, 2)),
                (41, 2, "qty_of_online_inverters", num(41, 2)),
                (49, 3, "firmware_length", vsl),
                (52, vsl, "firmware", text(52, vsl)),
            ]
    except (ValueError, IndexError) as err:
        return {"error": f"cannot map ecu_info answer: {err}"}

    end = len(data) - 4 if data.endswith(b"END\n") else len(data)
    known = sorted(fields)
    unknown = []
    pos = 0
    for start, length, _, _ in known:
        if start > pos:
            unknown.append((pos, start - pos))
        pos = max(pos, start + length)
    if pos < end:
        unknown.append((pos, end - pos))

    return {
        "known_fields": [
            {"offset": start, "length": length, "name": name, "value": value}
            for start, length, name, value in known
        ],
        "undecoded_bytes": [
            {
                "offset": start,
                "length": length,
                "hex": data[start : start + length].hex(),
                "as_int": int.from_bytes(data[start : start + length], "big"),
                "ascii": text(start, length),
            }
            for start, length in unknown
        ],
    }


async def query_socket(ipaddr, payload, timeout=10):
    """Send one command and read the full answer (until END or timeout)."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(ipaddr, PORT), timeout=timeout
    )
    try:
        writer.write(payload.encode("utf-8"))
        await writer.drain()
        data = b""
        while not data.endswith(b"END\n") and len(data) < 65536:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=timeout)
            if not chunk:
                break
            data += chunk
        return data
    finally:
        writer.close()
        await writer.wait_closed()


async def probe_socket(ipaddr, ecu_id):
    """Query every known socket command, one connection per command."""
    results = {}
    async with GLOBAL_ECU_LOCK:
        for name, payload in socket_commands(ecu_id):
            try:
                data = await query_socket(ipaddr, payload)
                results[name] = {"request": payload.strip(), **describe_frame(data)}
                if name == "ecu_info":
                    results[name]["byte_map"] = map_ecu_info(data)
            except (OSError, asyncio.TimeoutError) as err:
                results[name] = {"request": payload.strip(), "error": repr(err)}
            # The ECU does not like fast consecutive connections
            await asyncio.sleep(2)
    return results


def json_keys(value, prefix=""):
    """Return the structure of a JSON document (keys and value types)."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            out.update(json_keys(item, f"{prefix}{key}."))
        return out
    if isinstance(value, list):
        sample = json_keys(value[-1], f"{prefix}[-1].") if value else {}
        return {f"{prefix}[]": f"list of {len(value)}", **sample}
    return {prefix.rstrip("."): type(value).__name__}


async def probe_web(ipaddr):
    """GET the read-only local web pages and return their raw content."""
    results = {}
    headers = {"X-Requested-With": "XMLHttpRequest"}
    async with aiohttp.ClientSession() as session:
        for path in WEB_PATHS:
            url = f"http://{ipaddr}/{path}"
            try:
                async with session.get(url, headers=headers, timeout=15) as resp:
                    body = await resp.text(errors="replace")
                    entry = {
                        "status": resp.status,
                        "content_type": resp.headers.get("Content-Type"),
                        "length": len(body),
                    }
                    try:
                        parsed = json.loads(body)
                        entry["json_structure"] = json_keys(parsed)
                        entry["json"] = parsed
                    except ValueError:
                        text = re.sub(r"<script.*?</script>", " ", body, flags=re.S)
                        text = re.sub(r"<[^>]+>", " ", text)
                        entry["text"] = re.sub(r"\s+", " ", text).strip()[:MAX_TEXT]
                    results[path] = entry
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                results[path] = {"error": repr(err)}
    return results


async def async_get_config_entry_diagnostics(hass, entry):
    """Return diagnostics for a config entry."""
    ecu = hass.data[DOMAIN][entry.entry_id]["ecu"]
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    ecu_id = ecu.ecu.ecu_id

    diagnostics = {
        "config": async_redact_data(dict(entry.data), TO_REDACT),
        "ecu_id": ecu_id,
        "firmware": ecu.ecu.firmware,
        "parsed_data": coordinator.data,
        "cloud_state": async_redact_data(ecu.cloud_state or {}, TO_REDACT),
    }
    try:
        diagnostics["socket"] = await probe_socket(ecu.ipaddr, ecu_id)
    except Exception as err:  # pylint: disable=broad-except
        diagnostics["socket"] = {"error": repr(err)}
    if ecu_id and ecu_id.startswith(("215", "2162")):
        diagnostics["web"] = await probe_web(ecu.ipaddr)
    return diagnostics
