import os

import pytest

# Settings are read at import time, so these must be set before app modules load.
os.environ.setdefault("SESSION_SECRET", "test-secret-at-least-32-bytes-long!!")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "false")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "live: hits a real third-party API; needs credentials"
    )


@pytest.fixture
def pak_chn_payload() -> dict:
    """The ACTUAL Orizn response for PAK->CHN, captured from the live API.

    Pinned verbatim so that if Orizn changes its contract, our tests fail
    rather than our users' travel plans.
    """
    return {
        "passport": "PAK",
        "destination": "CHN",
        "requirement": "visa_required",
        "visa_free_days": None,
        "visa_required": True,
        "last_verified": "2026-05-08",
        "license": "evaluation — free plan is licensed for non-commercial use only.",
        "_hint": "For full details, use /api/v1/visa with an API key",
        "partner_links": [
            {"partner": "ekta", "kind": "insurance", "label": "Travel insurance"}
        ],
    }
