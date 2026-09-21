"""Load config/list.py (gitignored) via importlib — same pattern as recipe_pipeline."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from typing import Any


def _package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    """Directory containing list.py. Override with LIST_CONFIG_DIR."""
    env = os.environ.get("LIST_CONFIG_DIR")
    if env:
        return Path(env)
    return _package_root() / "config"


def _load_py_module(stem: str, *, required: bool = True) -> ModuleType | None:
    directory = config_dir()
    path = directory / f"{stem}.py"
    if not path.is_file():
        if required:
            raise FileNotFoundError(
                f"No config file {path} (copy {stem}.py.example to {stem}.py under {directory})"
            )
        return None
    spec = importlib.util.spec_from_file_location(f"listapi_config_{stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load config module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_absent(value: Any) -> Any:
    """Treat legacy empty-string config as unset (prefer None)."""
    if value == "":
        return None
    return value


def load_list_config() -> dict[str, Any]:
    """Return ``url`` and ``api_key`` from config/list.py (api_key may be None for Entra)."""
    mod = _load_py_module("list")
    url = _normalize_absent(getattr(mod, "url", None))
    api_key = _normalize_absent(getattr(mod, "api_key", None))
    return {"url": url, "api_key": api_key}
