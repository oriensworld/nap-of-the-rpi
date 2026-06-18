# ----------------------------------------------------------------------------------------------------
# config.py
# ----------------------------------------------------------------------------------------------------

"""
Configuration manager: YAML loader with defaults and env var substitution.

This module handles loading settings from config.yaml and providing typed access
to all configuration values. If a value is missing from the file, sensible defaults
are used. Environment variables like ${WEATHER_API_KEY} are substituted automatically.

Usage:
    from core.config import Config

    config = Config.load("config.yaml")
    print(config.laser.pattern)       # "blink"
    print(config.weather.api_key)     # value of $WEATHER_API_KEY env var
    print(config.pir.cooldown_seconds)  # 10
"""

# ----------------------------------------------------------------------------------------------------
from __future__ import annotations

import os
import re
from pathlib import Path

# We import yaml at the top — it's listed in our pyproject.toml dependencies
import yaml

# ----------------------------------------------------------------------------------------------------
# Default configuration values. If config.yaml is missing a key, these are used.
# This means the app can start even with an empty or partial config file.
DEFAULTS = {
    "pir": {
        "pin": 17,
        "cooldown_seconds": 10,
    },
    "laser": {
        "pin": 18,
        "pattern": "blink",
        "duration_seconds": 3.0,
        "blink_frequency_hz": 5.0,
        "pulse_rate_hz": 1.0,
    },
    "weather": {
        "api_key": "",
        "location": "New York,US",
        "units": "imperial",
    },
    "voice": {
        "wake_word": "hey pi",
        "model_path": "./models/vosk-model-small-en-us",
    },
    "audio": {
        "tts_speed": 150,
        "tts_voice": "en_US-lessac-medium",
        "tts_model_path": "./models/piper-voice-en-us",
        "bluetooth_device": "JBL Flip 6",
        "fallback_to_jack": True,
    },
    "system": {
        "log_level": "INFO",
        "log_file": "/var/log/nap-of-the-rpi.log",
        "log_max_bytes": 5242880,
        "log_backup_count": 3,
    },
}


# ----------------------------------------------------------------------------------------------------
class ConfigSection:
    """
    A section of configuration that allows attribute-style access.

    Instead of config["laser"]["pattern"], you can write config.laser.pattern.
    This is more readable and catches typos at development time.

    How it works:
        section = ConfigSection({"pin": 18, "pattern": "blink"})
        section.pin      # -> 18
        section.pattern  # -> "blink"
        section.missing  # -> raises AttributeError
    """

    def __init__(self, data: dict):
        # Store each key-value pair as an attribute on this object.
        # If a value is itself a dict, wrap it in another ConfigSection (recursive).
        for key, value in data.items():
            if isinstance(value, dict):
                setattr(self, key, ConfigSection(value))
            else:
                setattr(self, key, value)

    def __repr__(self) -> str:
        """Show a readable representation when printing (useful for debugging)."""
        attrs = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        return f"ConfigSection({attrs})"


# ----------------------------------------------------------------------------------------------------
class Config:
    """
    Application configuration with typed attribute access and sensible defaults.

    Loads from a YAML file, substitutes ${ENV_VAR} patterns, merges with defaults,
    and provides dot-notation access to all values.

    Usage:
        config = Config.load("config.yaml")
        config.laser.pattern          # "blink"
        config.pir.cooldown_seconds   # 10
        config.weather.api_key        # resolved from $WEATHER_API_KEY
    """

    # ------------------------------------------------------------------------------------------------
    def __init__(self, data: dict):
        """
        Initialize Config from a merged data dictionary.

        Each top-level key (pir, laser, weather, etc.) becomes a ConfigSection.
        """
        for key, value in data.items():
            if isinstance(value, dict):
                setattr(self, key, ConfigSection(value))
            else:
                setattr(self, key, value)

    # ------------------------------------------------------------------------------------------------
    @classmethod
    def load(cls, path: str = "config.yaml") -> Config:
        """
        Load config from YAML file with env var substitution and defaults.

        Process:
        1. Read the YAML file (if it exists)
        2. Merge with defaults (file values override defaults)
        3. Substitute ${ENV_VAR} patterns with actual environment variable values
        4. Return a Config object with dot-notation access

        Args:
            path: Path to the YAML config file. If it doesn't exist, all defaults are used.

        Returns:
            A Config object with all settings accessible via attributes.
        """
        # Start with a deep copy of defaults
        merged = _deep_copy(DEFAULTS)

        # Try to load the YAML file
        config_path = Path(path)
        if config_path.exists():
            with open(config_path) as f:
                file_data = yaml.safe_load(f)

            # If the file isn't empty, merge its values over the defaults
            if file_data and isinstance(file_data, dict):
                _deep_merge(merged, file_data)

        # Substitute ${ENV_VAR} patterns throughout all string values
        _substitute_env_vars(merged)

        return cls(merged)

    # ------------------------------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Show a readable representation when printing."""
        attrs = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        return f"Config({attrs})"


# ----------------------------------------------------------------------------------------------------
# Private helper functions (not part of the public API, just internal utilities)
# ----------------------------------------------------------------------------------------------------


def _deep_copy(data: dict) -> dict:
    """
    Create a deep copy of a nested dictionary.

    We need this so that modifying the merged config doesn't accidentally
    change our DEFAULTS dictionary (which should stay constant).
    """
    result = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result[key] = _deep_copy(value)
        else:
            result[key] = value
    return result


def _deep_merge(base: dict, override: dict) -> None:
    """
    Recursively merge 'override' into 'base' (modifies base in-place).

    For nested dicts, we merge recursively. For everything else, override wins.

    Example:
        base = {"laser": {"pin": 18, "pattern": "blink"}}
        override = {"laser": {"pattern": "pulse"}}
        _deep_merge(base, override)
        # base is now {"laser": {"pin": 18, "pattern": "pulse"}}
        # Note: pin is preserved because override didn't specify it
    """
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            # Both are dicts — merge recursively
            _deep_merge(base[key], value)
        else:
            # Override the value
            base[key] = value


def _substitute_env_vars(data: dict) -> None:
    """
    Replace ${ENV_VAR} patterns in string values with actual environment variable values.

    This lets you write api_key: "${WEATHER_API_KEY}" in config.yaml and have it
    automatically replaced with the value of the WEATHER_API_KEY environment variable.

    If the environment variable is not set, the pattern is replaced with an empty string.

    The regex pattern r'\\$\\{([^}]+)\\}' matches:
        ${ — literal dollar sign and opening brace
        ([^}]+) — one or more characters that aren't } (this is the variable name)
        } — literal closing brace
    """
    # Pattern to match ${SOMETHING}
    env_pattern = re.compile(r"\$\{([^}]+)\}")

    for key, value in data.items():
        if isinstance(value, dict):
            # Recurse into nested dicts
            _substitute_env_vars(value)
        elif isinstance(value, str):
            # Find all ${VAR} patterns in this string and replace them
            def replace_match(match):
                var_name = match.group(1)  # Extract the variable name
                return os.environ.get(var_name, "")  # Get value or empty string

            data[key] = env_pattern.sub(replace_match, value)
