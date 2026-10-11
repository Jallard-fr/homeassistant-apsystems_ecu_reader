"""const.py"""

DOMAIN = "apsystems_ecu_reader"

SOLAR_ICON = "mdi:solar-power"
FREQ_ICON = "mdi:sine-wave"
SIGNAL_ICON = "mdi:signal"
CACHE_ICON = "mdi:cached"
POWER_ICON = "mdi:power"
SOLAR_PANEL_ICON = "mdi:solar-panel"
CACHE_COUNTER_ICON = "mdi:counter"
ECU_REBOOT_ICON = "mdi:restart"
FROM_GRID_ICON = "mdi:transmission-tower-export"
CONSUMED_ICON = "mdi:transmission-tower"
DOWNLOAD_ICON = "mdi:download"
TO_GRID_ICON = "mdi:transmission-tower-import"
HOME_ICON = "mdi:home-lightning-bolt"


# Config flow schema. These are also translated through json translations
KEYS = [
    "ecu_host",
    "scan_interval",
    "port_retries",
    "cache_reboot",
    "show_graphs",
    "wifi_ssid",
    "wifi_password",
    "cloud_app_id",
    "cloud_app_secret",
    "cloud_sid",
    "cloud_interval",
]
CLOUD_KEYS = KEYS[7:10]

# Model maps for ECU and inverter types
ECU_MODEL_MAP = {
    "2160": "ECU-R",
    "2162": "ECU-R-Pro",
    "2163": "ECU-B",
    "2150": "ECU-C",
    "2030": "ECU-3",
}

INVERTER_MODEL_MAP = {
    "10": "YC500 series",
    "40": "YC600 series",
    "50": "YC1000 series",
    "70": "DS3 series",
    "80": "QS1 series",
    "90": "QT2 series",
}

PORT = 8899
DEFAULT_RECV_SIZE = 1024
SETUP_DELAY_SECONDS = 10
DEFAULT_SCAN_INTERVAL = 300
DEFAULT_PORT_RETRIES = 2
DEFAULT_CACHE_REBOOT = 3

# APsystems OpenAPI (EMA cloud)
CLOUD_BASE_URL = "https://api.apsystemsema.com:9282"
CLOUD_PERIODS = ["today", "lifetime"]
CLOUD_METER_FIELDS = ["produced", "consumed", "imported", "exported"]
# Default APsystems quota is 1000 calls/month: poll every 60 minutes (~744 calls)
# and stop polling once the monthly budget is reached.
DEFAULT_CLOUD_INTERVAL = 60  # minutes
MIN_CLOUD_INTERVAL = 15  # minutes
CLOUD_MONTHLY_BUDGET = 950
