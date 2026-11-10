"""Saved output from a real model run.

A checkout with no API key replays these files. They are the classifications,
contract reviews, claims, and letters from one live scan, plus the price and
usage records the Recoveries screen reads.
"""

from __future__ import annotations

import json

from .config import REPO_ROOT, Settings
from .models import ContractFinding, ImporterCase, Letter, LineLabel, PriceAnalysis, Usage, VendorClaim
from .run import PipelineOutput

LIVE_FILES = {
    "classifications": "classifications.json",
    "contract_reviews": "contract_reviews.json",
    "claims": "claims.json",
    "letters": "letters.json",
    "prices": "prices.json",
    "importer_cases": "importer_cases.json",
    "usage": "usage.json",
}


def live_results_dir():
    return REPO_ROOT / "data" / "live_results"


def saved_available() -> bool:
    folder = live_results_dir()
    return all((folder / name).is_file() for name in LIVE_FILES.values())


def replay_saved(settings: Settings) -> bool:
    """Replay the saved run when nobody asked for keyword rules and no key is set."""
    return not settings.demo_mode and not settings.anthropic_api_key.strip() and saved_available()


def load_saved_output() -> PipelineOutput:
    folder = live_results_dir()
    raw = {key: json.loads((folder / name).read_text()) for key, name in LIVE_FILES.items()}
    return PipelineOutput(
        labels=[LineLabel.model_validate(row) for row in raw["classifications"]],
        claims=[VendorClaim.model_validate(row) for row in raw["claims"]],
        letters=[Letter.model_validate(row) for row in raw["letters"]],
        importer_cases=[ImporterCase.model_validate(row) for row in raw["importer_cases"]],
        prices=PriceAnalysis.model_validate(raw["prices"]),
        contracts={name: ContractFinding.model_validate(row) for name, row in raw["contract_reviews"].items()},
        usage=Usage.model_validate(raw["usage"]),
    )
