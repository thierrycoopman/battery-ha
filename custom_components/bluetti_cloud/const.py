"""Constants for the Bluetti Cloud integration."""

DOMAIN = "bluetti_cloud"

APP_ID = "1783AF460D4D0615365940C9D3A"

GW_URL = "https://gw.bluettipower.com"
GW_PRIMARY_URL = "https://gwpry.bluettipower.com"

DEFAULT_SCAN_INTERVAL = 30  # seconds — REST-only fallback
MQTT_SCAN_INTERVAL = 60  # seconds — REST interval when MQTT is active
MQTT_POLL_INTERVAL = 10  # seconds between full MQTT polling cycles
MQTT_REQUEST_TIMEOUT = 3.0  # seconds to wait for a single MQTT response
MQTT_RECONNECT_MIN = 30  # seconds — initial reconnect delay
MQTT_RECONNECT_MAX = 300  # seconds — max reconnect delay (5 minutes)
