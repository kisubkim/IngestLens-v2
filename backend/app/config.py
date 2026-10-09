import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

ROOT = Path(__file__).resolve().parents[2]
# Written by the settings screen (storage locations). Environment variables and .env win over it.
SETTINGS_FILE = Path(os.environ.get("RAG_SETTINGS_FILE") or ROOT / "config" / "settings.local.yaml")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=ROOT / ".env", extra="ignore", yaml_file=SETTINGS_FILE)

    data_dir: Path = ROOT / "data"
    db_url: str = ""  # empty = SQLite under data_dir
    qdrant_url: str = ""  # empty = embedded Qdrant under data_dir/qdrant
    models_file: Path = ROOT / "config" / "models.yaml"
    rules_file: Path = ROOT / "config" / "strategy_rules.yaml"
    # PDF engine (ToolPDF, a separate program called over HTTP). "shared": the engine mounts this data_dir as its
    # TOOLPDF_SHARED_ROOT and files are named by their path under it; "http": files are uploaded and named by sha256.
    toolpdf_url: str = "http://127.0.0.1:8095"
    toolpdf_api_key: str = ""
    toolpdf_transfer: str = "http"
    toolpdf_timeout_s: float = 600
    api_key: str = ""  # Bearer token for the ingest API (/api/ingest, Open WebUI loader); empty = no auth
    admin_hosts: str = ""  # extra IPs/CIDRs treated as "this machine" for settings changes (Docker bridge gateway)
    data_dir_hint: str = ""  # shown when data_dir is locked, e.g. how the Docker volume decides the data folder
    ingest_wait_seconds: float = 3600  # how long the Open WebUI loader waits for a run before giving up
    evals_dir: Path = ROOT / "evals" / "results"  # result files of scripts/eval_*.py shown by the comparison screen

    @field_validator("data_dir", "models_file", "rules_file", "evals_dir")
    @classmethod
    def _from_repo_root(cls, v: Path) -> Path:
        """Relative paths (e.g. RAG_MODELS_FILE=config/models.windows.yaml in .env) are taken from the repository root,
        not from the folder the server happens to start in. The settings screen does the same for data_dir."""
        v = Path(v).expanduser()
        return v if v.is_absolute() else ROOT / v

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return init_settings, env_settings, dotenv_settings, YamlConfigSettingsSource(settings_cls), file_secret_settings

    @property
    def database_url(self) -> str:
        return self.db_url or f"sqlite:///{(self.data_dir / 'rag.db').as_posix()}"

    def stored_path(self, path: Path) -> str:
        """Paths under data_dir are stored relative to it, so the whole folder can be moved."""
        try:
            return Path(path).resolve().relative_to(self.data_dir.resolve()).as_posix()
        except ValueError:
            return str(path)

    def resolve(self, stored: str) -> Path:
        p = Path(stored)
        return p if p.is_absolute() else self.data_dir / p


settings = Settings()


@lru_cache
def models_cfg() -> dict:
    return yaml.safe_load(settings.models_file.read_text(encoding="utf-8"))


def rules_base() -> dict:
    """The rules shipped in config/strategy_rules.yaml (or RAG_RULES_FILE)."""
    return yaml.safe_load(settings.rules_file.read_text(encoding="utf-8"))


def rules_override_path() -> Path:
    """Values changed on the rules screen. In the data folder: writable under Docker and Singularity, and backed up
    with the documents. Holds only the changed keys, so new defaults in a later version still apply."""
    return settings.data_dir / "strategy_rules.override.yaml"


def rules_override() -> dict:
    p = rules_override_path()
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


# Why the override file was ignored the last time the rules were loaded ("" when it was used or absent).
RULES_OVERRIDE_ERROR = {"message": ""}


def merge_rules(base: dict, override: dict) -> dict:
    """Dicts merge key by key; any other value (numbers, strings, the profiler rule list) is replaced whole."""
    out = dict(base)
    for k, v in override.items():
        out[k] = merge_rules(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


@lru_cache
def rules_cfg() -> dict:
    """Effective rules: the shipped file plus the screen's overrides. The rules screen clears this cache on save,
    so the next agent step reads the new values without a restart. An override that cannot be read or would give
    values the agents cannot use (e.g. edited by hand) is ignored, so documents still process with the shipped
    rules; the rules screen shows why."""
    from .tools.rules_schema import validate  # imports nothing from here

    base = rules_base()
    RULES_OVERRIDE_ERROR["message"] = ""
    try:
        merged = merge_rules(base, rules_override())
        errors = validate(merged)
    except Exception as e:  # unreadable YAML, wrong shapes
        errors = [f"{type(e).__name__}: {e}"]
    if errors:
        RULES_OVERRIDE_ERROR["message"] = "; ".join(errors[:5])
        return base
    return merged


def rules_version() -> str:
    """Short hash of the effective rules, recorded per run so runs made with different rules can be told apart."""
    return hashlib.sha256(json.dumps(rules_cfg(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
