"""Constants for the CTEK CCU control driver."""

DOMAIN = "ctek_ccu"

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_PREFIX = "prefix"
CONF_CONNECTORS = "connectors"
CONF_MAX_CURRENT = "max_current_a"

DEFAULT_PREFIX = "ctek"
DEFAULT_CONNECTORS = 2
DEFAULT_MAX_CURRENT = 16

# OCPP charging-profile scaffolding. We only ever write a TxDefaultProfile per
# connector; the limit is what blocks (0 A) or permits (N A) charging. Because
# OCPP composes stacked profiles by taking the LOWEST limit, this can only ever
# restrict further than whatever the upstream central system (e.g. a Ferroamp
# EnergyHub doing load balancing) already allows — never exceed it.
PROFILE_PURPOSE = "TxDefaultProfile"
PROFILE_KIND = "Relative"
RATE_UNIT = "A"

# Must match OPTION_KEY in stats.py. Kept here so config_flow can build its
# schema without importing stats.py, which pulls in Home Assistant.
CONF_SEND_STATISTICS = "send_statistics"
