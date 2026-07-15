"""Centralized, environment-driven configuration. Production deploys should
set these via the platform's secrets/config manager rather than editing code."""
import os

# Comma-separated list of allowed origins. "*" only for local dev.
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")

# If set, all mutating/investigate endpoints require `Authorization: Bearer <token>`.
API_AUTH_TOKEN = os.environ.get("API_AUTH_TOKEN", "")

CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.6"))

# Guardrails against runaway/abusive payloads.
MAX_FIELD_ITEMS = int(os.environ.get("MAX_FIELD_ITEMS", "500"))
MAX_ITEM_LENGTH = int(os.environ.get("MAX_ITEM_LENGTH", "20000"))

# Per-incident cost cap (USD). Investigation aborts (fails closed) above this.
MAX_COST_PER_INCIDENT_USD = float(os.environ.get("MAX_COST_PER_INCIDENT_USD", "1.00"))

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data.db"))

LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "3"))
LLM_TIMEOUT_SECONDS = int(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))
