"""Settings (.env), paths and YAML config loaders."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(os.environ.get("FLIGHTREC_ROOT") or Path(__file__).resolve().parents[2])
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
CORPUS_DIR = DATA_DIR / "corpus"
CORPUS_SRC_DIR = CORPUS_DIR / "src"  # markdown sources of the PDF documents
EVAL_DIR = DATA_DIR / "eval"
DOCS_DIR = ROOT / "docs"

FAKE_PREFIX = "fake-"


def load_env_file(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from .env into os.environ without overriding existing variables.

    Values are never printed. google-genai / ADK read GOOGLE_API_KEY from the environment.
    """
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v:  # an empty value (e.g. GOOGLE_API_KEY=) is treated as unset
            os.environ.setdefault(k.strip(), v)


load_env_file()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    google_api_key: str = ""
    agent_model: str = "TBD"
    judge_model: str = "TBD"
    embed_model: str = "TBD"
    database_url: str = "postgresql+psycopg://flightrec:flightrec@127.0.0.1:5432/flightrec"
    scale_tier: str = "TBD"
    max_llm_calls_per_run: int = 25
    chunk_chars: int = 1200
    chunk_overlap: int = 150
    retrieve_top_k: int = 5
    prompt_version: str = "v1"


def settings() -> Settings:
    """Fresh settings each call so CLI flags that set env vars take effect."""
    return Settings()


def _yaml(name: str) -> dict:
    p = CONFIG_DIR / name
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def norm_model(model: str) -> str:
    return model.removeprefix("models/")


@lru_cache(maxsize=1)
def load_limits() -> dict:
    return {norm_model(str(k)): v for k, v in _yaml("limits.yaml").items()}


@lru_cache(maxsize=1)
def load_pricing() -> dict:
    return _yaml("pricing.yaml")


def load_scale(tier: str | None = None) -> dict:
    tier = tier or settings().scale_tier
    data = _yaml("scale.yaml")
    if tier not in data:
        raise SystemExit(f"SCALE_TIER={tier!r} not in config/scale.yaml (run scripts/model_probe.py first)")
    return data[tier]


def load_facts() -> dict:
    return yaml.safe_load((DATA_DIR / "facts.yaml").read_text(encoding="utf-8"))


def is_fake(model: str | None) -> bool:
    return bool(model) and norm_model(model).startswith(FAKE_PREFIX)
