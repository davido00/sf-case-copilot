"""
Where Cases and Knowledge Articles come from.

This is the SEAM. Everything else in the project -- retrieval, the tools, the
agent -- asks for data through these five functions and has no idea whether the
answer came from a JSON file or from a live Salesforce org.

Set DATA_SOURCE in .env to switch:
    DATA_SOURCE=mock         (default) read data/sample_cases.json
    DATA_SOURCE=salesforce   query the org configured by the SF_* variables

Nothing downstream changes. That is the entire point of having built it this
way in Step 3, and it means you can develop offline for free and then point the
same agent at a real org.
"""

import json
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_SOURCE = os.environ.get("DATA_SOURCE", "mock").strip().lower()

DATA_FILE = Path(__file__).parent.parent / "data" / "sample_cases.json"


def using_salesforce() -> bool:
    """True when we are pointed at a real org rather than the JSON file."""
    return DATA_SOURCE == "salesforce"


# ---------------------------------------------------------------------------
# Mock backend -- the JSON file
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_json() -> dict:
    """Read and parse the mock data once per process."""
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Salesforce backend -- cached so one run does not re-query for every search
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _sf_cases() -> tuple[dict, ...]:
    # Imported here, not at the top, so that mock mode never needs
    # simple-salesforce or a .env full of credentials.
    import sf_client

    return tuple(sf_client.fetch_cases())


@lru_cache(maxsize=1)
def _sf_articles() -> tuple[dict, ...]:
    import sf_client

    return tuple(sf_client.fetch_articles())


# ---------------------------------------------------------------------------
# The public interface. These five functions are all anything else may call.
# ---------------------------------------------------------------------------


def list_cases() -> list[dict]:
    """Every Case available from the current data source."""
    if using_salesforce():
        return list(_sf_cases())
    return _load_json()["cases"]


def get_case(case_number: str) -> dict | None:
    """One Case by its CaseNumber, or None if there is no such Case.

    Returning None rather than raising is deliberate: the agent calls this as
    a tool, and "that case does not exist" is an answer the model needs to be
    able to receive and act on, not a crash.
    """
    if using_salesforce():
        # Ask the org directly rather than scanning the cached page of cases --
        # the case we want may be older than the LIMIT we fetched.
        import sf_client

        return sf_client.fetch_case(case_number)

    for case in list_cases():
        if case["CaseNumber"] == case_number:
            return case
    return None


def list_articles() -> list[dict]:
    """Every published Knowledge Article from the current data source."""
    if using_salesforce():
        return list(_sf_articles())
    return _load_json()["knowledge_articles"]


def get_article(article_number: str) -> dict | None:
    """One Knowledge Article by its ArticleNumber, or None."""
    for article in list_articles():
        if article["ArticleNumber"] == article_number:
            return article
    return None


def ground_truth() -> dict[str, list[str]]:
    """Which articles SHOULD match each case. Mock data only.

    This is test scaffolding we wrote in Step 3, not Salesforce data, so a real
    org has nothing to offer here and returns an empty mapping.
    """
    if using_salesforce():
        return {}
    raw = _load_json()["_eval_ground_truth"]
    return {k: v for k, v in raw.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Writing drafts back (Step 7)
#
# Reads had a seam; writes get one too. The agent calls save_draft() and does
# not know whether the draft landed in a Python dict or on a real Case.
# ---------------------------------------------------------------------------

# What was saved this session, keyed by CaseNumber. In mock mode this IS the
# storage; in Salesforce mode it is just a local record of what we wrote, so
# the CLI can show it back without another round trip.
_SAVED: dict[str, dict] = {}


def save_draft(case_number: str, draft_text: str) -> dict:
    """Save a drafted resolution against a Case.

    Returns {"ok": bool, "detail": str} -- a sentence the agent can read,
    never an exception, for the same reason the read tools work that way.
    """
    case = get_case(case_number)
    if case is None:
        return {"ok": False, "detail": f"No case found with number {case_number}."}

    if not draft_text.strip():
        return {"ok": False, "detail": "The draft was empty, so nothing was saved."}

    if using_salesforce():
        import sf_client

        # If we already wrote a comment for this case, UPDATE it rather than
        # adding another. The agent sometimes re-drafts after reading its own
        # word count, and without this each attempt leaves a superseded draft
        # on the record. One case, one current draft.
        existing = _SAVED.get(case_number, {}).get("comment_id")

        try:
            if existing:
                result = sf_client.update_case_comment(existing, draft_text)
                comment_id, verb = existing, "Updated"
            else:
                result = sf_client.create_case_comment(case["Id"], draft_text)
                comment_id, verb = result["id"], "Saved as"
        except Exception as exc:
            # Surface the org's own message -- it names the field or rule that
            # rejected the write, which is what a person needs to fix it.
            return {"ok": False, "detail": f"Salesforce rejected the write: {exc}"}

        _SAVED[case_number] = {"text": draft_text, "comment_id": comment_id}
        detail = (
            f"{verb} an internal Case Comment on case {case_number} "
            f"(comment {comment_id}, not visible to the customer). "
            "Re-drafting again will replace this same comment, not add another."
        )
        if result["truncated"]:
            detail += " NOTE: the draft exceeded 4000 characters and was truncated."
        return {"ok": True, "detail": detail}

    _SAVED[case_number] = {"text": draft_text, "comment_id": None}
    return {
        "ok": True,
        "detail": f"Draft saved locally against case {case_number} (mock mode).",
    }


def saved_drafts() -> dict[str, dict]:
    """Everything saved this session, for the CLI to display."""
    return _SAVED


def forget_draft(case_number: str) -> None:
    """Drop our record of a saved draft, so the next save creates a NEW comment.

    The service calls this before each request. Within one agent run, re-drafting
    should replace the comment it just wrote; a fresh request from a user who
    clicked the button again should leave a new one rather than silently
    overwriting what a colleague is reading.
    """
    _SAVED.pop(case_number, None)


def get_case_by_id(case_id: str) -> dict | None:
    """One Case by its Salesforce Id, or None. The chat endpoint uses this."""
    if using_salesforce():
        import sf_client

        return sf_client.fetch_case_by_id(case_id)

    for case in list_cases():
        # Match 15-char Ids against our 18-char mock Ids too.
        if case["Id"] == case_id or case["Id"].startswith(case_id):
            return case
    return None
