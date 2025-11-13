"""Configuration loading utilities for auto_break_player."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULTS: Dict[str, Any] = {
    "secret_key": "dev-secret-key",
    "host": "127.0.0.1",
    "port": 8000,
    "db_path": "auto_break_player.db",
    "music_dir": "music",
    "logs_dir": "logs",
    "max_upload_mb": 50,
    "allowed_extensions": [".mp3", ".wav"],
    "vlc_backend": "auto",
    "volume_default": 70,
    "session_default_minutes": 15,
    "cors_origins": ["*"],
    "gpio": {
        "enabled": True,
        "relay_pin": 17,
        "active_high": True,
    },
    "ui": {
        "theme": "dark",
    },
}


def _merge_dict(base: Dict[str, Any], other: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge two dictionaries and return the result."""
    for key, value in other.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            base[key] = _merge_dict(dict(base[key]), value)
        else:
            base[key] = value
    return base


def load_config(path: str | Path = "config.yaml") -> Dict[str, Any]:
    """Load configuration from YAML file and merge with defaults."""
    config = deepcopy(DEFAULTS)
    config_path = Path(path)
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ValueError("Config file must contain a mapping at the root level")
        config = _merge_dict(config, data)
    # Ensure directories are stored as strings for compatibility.
    config["music_dir"] = str(config["music_dir"])
    config["logs_dir"] = str(config["logs_dir"])
    config["allowed_extensions"] = [ext.lower() for ext in config["allowed_extensions"]]
    return config


__all__ = ["DEFAULTS", "load_config"]
