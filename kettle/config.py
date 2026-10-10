"""Paths, config.toml and .env loading."""

import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_FILE = ROOT / "questions.toml"
CONFIG_FILE = ROOT / "config.toml"
ENV_FILE = ROOT / ".env"
STATE_FILE = ROOT / "state.json"
LOG_FILE = ROOT / "probes.jsonl"
LOCK_FILE = ROOT / ".kettle.lock"
WEB_DIR = ROOT / "web"


class ConfigError(Exception):
    pass


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_config():
    if not CONFIG_FILE.exists():
        raise ConfigError("config.toml 不存在:先 cp config.example.toml config.toml 并填入 bark_key")
    with open(CONFIG_FILE, "rb") as f:
        return tomllib.load(f)


def load_config_or_exit():
    try:
        return load_config()
    except ConfigError as e:
        sys.exit(str(e))


def load_dotenv():
    """Parse simple KEY=VALUE lines from .env. Missing file yields {}."""
    if not ENV_FILE.exists():
        return {}
    env = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key] = value
    return env
