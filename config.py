"""Application configuration.

Secrets are read from the environment. No credentials are logged or committed.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent


def _as_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _as_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _as_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


class Config:
    HOST = os.environ.get("HOST", "0.0.0.0")
    PORT = _as_int("PORT", 8000)

    FLASK_ENV = os.environ.get("FLASK_ENV", "production")
    DEBUG = _as_bool("FLASK_DEBUG", False)
    TESTING = False

    DATABASE_URL = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'email_validator.db'}"
    )

    MAX_CONTENT_LENGTH = _as_int("MAX_CONTENT_LENGTH", 25 * 1024 * 1024)
    MAX_EMAILS_PER_JOB = _as_int("MAX_EMAILS_PER_JOB", 100_000)

    JOB_BATCH_SIZE = _as_int("JOB_BATCH_SIZE", 200)
    WORKER_CONCURRENCY = _as_int("WORKER_CONCURRENCY", 8)
    DNS_TIMEOUT = _as_int("DNS_TIMEOUT", 3)
    RATE_LIMIT_DELAY = _as_float("RATE_LIMIT_DELAY", 0.15)
    WORKER_RATE_LIMIT_PER_SECOND = _as_int("WORKER_RATE_LIMIT_PER_SECOND", 60)
    RATE_LIMIT_MAX = _as_int("RATE_LIMIT_MAX", 120)

    ENABLE_CATCHALL_PROBE = _as_bool("ENABLE_CATCHALL_PROBE", False)

    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")

    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    JSON_SORT_KEYS = False
