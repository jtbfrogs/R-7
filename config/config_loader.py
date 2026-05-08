"""
config/config_loader.py
───────────────────────
Loads configuration from YAML files, merges defaults with local overrides,
and exposes a single `get_config()` call used everywhere in the project.

Loading order (later values win):
  1. config/default_config.yaml   — version-controlled defaults
  2. config/local_config.yaml     — personal overrides (.gitignored)
  3. Environment variables        — PREFIX__KEY=value  (future feature)

Usage
─────
    from config.config_loader import get_config
    cfg = get_config()
    port = cfg["roomba"]["port"]
    model = cfg["ai"]["model"]

If a key is missing from local_config.yaml, the default is used automatically.
This means you only need to put the settings you want to change in local_config.yaml.
"""

import copy
import os
from pathlib import Path
from typing import Any

# ─── Try importing PyYAML ─────────────────────────────────────────────────────
try:
    import yaml
except ImportError:
    raise ImportError(
        "PyYAML is required for the config system.\n"
        "Install it with:  pip install pyyaml"
    )

# ─── File paths ───────────────────────────────────────────────────────────────
_PROJECT_ROOT   = Path(__file__).parent.parent
_DEFAULT_CONFIG = _PROJECT_ROOT / "config" / "default_config.yaml"
_LOCAL_CONFIG   = _PROJECT_ROOT / "config" / "local_config.yaml"

# ─── Singleton cache ──────────────────────────────────────────────────────────
_config_cache: dict[str, Any] | None = None


def _deep_merge(base: dict, override: dict) -> dict:
    """
    Recursively merge `override` into `base`.
    Keys in `override` win.  Missing keys fall back to `base`.
    Works for nested dicts (e.g. roomba.port, ai.model).
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Recurse into nested sections
            result[key] = _deep_merge(result[key], value)
        else:
            # Override scalar or list
            result[key] = copy.deepcopy(value)
    return result


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Read a YAML file and return its contents as a dict."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def load_config(force_reload: bool = False) -> dict[str, Any]:
    """
    Load and merge the configuration files.

    Parameters
    ----------
    force_reload : if True, discard the cached config and reload from disk.
                   Useful during testing or if you hot-reload at runtime.

    Returns
    -------
    dict — the fully merged configuration
    """
    global _config_cache
    if _config_cache is not None and not force_reload:
        return _config_cache

    # Always start from the defaults
    if not _DEFAULT_CONFIG.exists():
        raise FileNotFoundError(
            f"Default config not found: {_DEFAULT_CONFIG}\n"
            "This file must exist.  Did you clone the repo correctly?"
        )
    config = _load_yaml_file(_DEFAULT_CONFIG)

    # Merge local overrides if they exist
    if _LOCAL_CONFIG.exists():
        local = _load_yaml_file(_LOCAL_CONFIG)
        config = _deep_merge(config, local)

    _config_cache = config
    return _config_cache


# Convenience alias — most modules only call get_config()
def get_config() -> dict[str, Any]:
    """
    Return the merged configuration dict (cached after first call).

    Example
    -------
        cfg = get_config()
        print(cfg["roomba"]["port"])     # → "auto"
        print(cfg["ai"]["model"])        # → "tinyllama"
    """
    return load_config()


def get(section: str, key: str, default: Any = None) -> Any:
    """
    Shorthand to get a single value without indexing twice.

    Example
    -------
        port  = get("roomba", "port")
        model = get("ai", "model", "tinyllama")
    """
    cfg = get_config()
    return cfg.get(section, {}).get(key, default)


def dump_config() -> str:
    """
    Return the current config as a formatted YAML string.
    Useful for logging the active config at startup.
    """
    return yaml.dump(get_config(), default_flow_style=False, sort_keys=True)


# ─── Quick self-test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Active Configuration ===")
    print(dump_config())
