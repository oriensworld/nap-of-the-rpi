"""Configuration manager: YAML loader with defaults and env var substitution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Config:
    """Application configuration with typed access and sensible defaults."""

    @classmethod
    def load(cls, path: str = "config.yaml") -> Config:
        """Load config from YAML file with env var substitution and defaults."""
        raise NotImplementedError
