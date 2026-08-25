"""
Reads the mock Salesforce data in data/sample_cases.json.

This module exists to be a SEAM. Every later step asks for Cases and Articles
through these functions instead of touching the JSON file directly. In Step 6
we rewrite the insides of these functions to call Salesforce, and nothing that
depends on them has to change.

That is the same instinct as putting SOQL behind a selector class in Apex
rather than scattering queries through your triggers.
"""

import json
from functools import lru_cache
from pathlib import Path

# Path to the JSON, worked out relative to THIS file rather than to whatever
# directory you happen to run python from. `__file__` is this file's path, so
# .parent is src/, and .parent.parent is the repo root.
DATA_FILE = Path(__file__).parent.parent / "data" / "sample_cases.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    """Read and parse the JSON file.

    `@lru_cache` means the file is read from disk once; every call after the
    first gets the same parsed dict back. Cheap, and it keeps the rest of the
    module from worrying about when to load.
    """
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def list_cases() -> list[dict]:
    """Every Case in the mock data."""
    return _load()["cases"]


def get_case(case_number: str) -> dict | None:
    """One Case by its CaseNumber, or None if there is no such Case.

    Returning None rather than raising is deliberate: in Step 5 the agent will
    call this as a tool, and 'that case does not exist' is an answer the model
    needs to be able to receive and act on, not a crash.
    """
    for case in list_cases():
        if case["CaseNumber"] == case_number:
            return case
    return None


def list_articles() -> list[dict]:
    """Every Knowledge Article in the mock data."""
    return _load()["knowledge_articles"]


def get_article(article_number: str) -> dict | None:
    """One Knowledge Article by its ArticleNumber, or None."""
    for article in list_articles():
        if article["ArticleNumber"] == article_number:
            return article
    return None


def ground_truth() -> dict[str, list[str]]:
    """Which articles SHOULD match each case. Test scaffolding, not SF data.

    Step 4 uses this to measure whether retrieval actually works, instead of
    us reading the output and deciding it looks about right.
    """
    raw = _load()["_eval_ground_truth"]
    return {k: v for k, v in raw.items() if not k.startswith("_")}
