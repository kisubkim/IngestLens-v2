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


@lru_cache
def rules_cfg() -> dict:
    return yaml.safe_load(settings.rules_file.read_text(encoding="utf-8"))
