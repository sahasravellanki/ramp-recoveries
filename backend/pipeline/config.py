"""Settings. Model ids are read from the environment, never hardcoded at the call site."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]

# The IEEPA tariffs struck down in February 2026.
WINDOW_START = date(2025, 2, 4)
WINDOW_END = date(2026, 2, 20)

BUYER_NAME = "Sunbird Cafe Group"
SIGN_OFF = "Accounts Payable, Sunbird Cafe Group"

# Math checks. A cent of rounding is normal; more than this means the bill is wrong.
LINE_TOLERANCE = "0.02"
TOTAL_TOLERANCE = "0.05"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        extra="ignore",
        populate_by_name=True,
    )

    anthropic_api_key: str = ""
    demo_mode: bool = False
    tier1_model: str = Field(
        default="claude-haiku-4-5",
        validation_alias=AliasChoices("RECOVERIES_MODEL_TIER1", "tier1_model"),
    )
    tier2_model: str = Field(
        default="claude-sonnet-4-5",
        validation_alias=AliasChoices("RECOVERIES_MODEL_TIER2", "tier2_model"),
    )
    data_dir: Path = Path("../data")

    @property
    def use_demo(self) -> bool:
        """Demo rules when asked, and also when there is no key, so a demo never breaks."""
        return self.demo_mode or not self.anthropic_api_key.strip()

    @property
    def demo_reason(self) -> str:
        if self.demo_mode:
            return "DEMO_MODE=1"
        return "no API key"

    def resolved_data_dir(self) -> Path:
        raw = Path(self.data_dir)
        if raw.is_absolute():
            return raw
        for candidate in (Path.cwd() / raw, BACKEND_DIR / raw, REPO_ROOT / "data"):
            if candidate.exists():
                return candidate.resolve()
        return (REPO_ROOT / "data").resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
