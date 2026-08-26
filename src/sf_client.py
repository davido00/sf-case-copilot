"""
Step 6: talk to a real Salesforce org.

The job of this file is NARROW: connect, run SOQL, and hand back dictionaries
that look exactly like the ones in data/sample_cases.json. Same keys, same
shapes. Everything downstream -- retrieval, tools, the agent -- then works
against a live org without a single change.

That is why we put data_store.py in front of the JSON back in Step 3. This is
the payoff.
"""

import html
import os
import re
from functools import lru_cache

from dotenv import load_dotenv
from simple_salesforce import Salesforce

load_dotenv()

# Which custom rich-text field on Knowledge__kav holds the article body.
# Salesforce ships Knowledge__kav with Title/Summary/UrlName and expects you to
# add your own body field, so the name differs between orgs. Everything
# downstream reads the key "Answer__c" regardless -- we normalise to it below.
BODY_FIELD = os.environ.get("SF_KNOWLEDGE_BODY_FIELD", "Answer__c")

# "login" for production and Developer/Trailhead orgs, "test" for sandboxes.
DOMAIN = os.environ.get("SF_DOMAIN", "login")


class SalesforceConfigError(RuntimeError):
    """Raised when the .env is missing something we need."""


@lru_cache(maxsize=1)
def get_connection() -> Salesforce:
    """Connect to Salesforce, reusing the same session for the whole process.

    Two auth modes, tried in this order:

    1. ACCESS TOKEN (preferred). Set SF_ACCESS_TOKEN and SF_INSTANCE_URL. This
       is plain OAuth -- no SOAP involved, no security token needed. Get them
       from the Salesforce CLI:

           sf org login web --alias play
           sf org display --target-org play --json

       and copy `accessToken` and `instanceUrl` from the output.

    2. USERNAME + PASSWORD + SECURITY TOKEN (legacy). Simple, but it goes
       through the SOAP login() endpoint, which is DISABLED BY DEFAULT in
       newly created orgs and which Salesforce is retiring in Summer '27.
       If you hit "SOAP API login() is disabled by default in this org",
       either enable it (Setup > User Interface > Enable SOAP API login())
       or switch to mode 1.
    """
    access_token = os.environ.get("SF_ACCESS_TOKEN")
    instance_url = os.environ.get("SF_INSTANCE_URL")

    if access_token and instance_url:
        # session_id IS the OAuth access token -- simple-salesforce's naming
        # predates OAuth, but it sends it as a normal Bearer token.
        return Salesforce(instance_url=instance_url, session_id=access_token)

    username = os.environ.get("SF_USERNAME")
    password = os.environ.get("SF_PASSWORD")
    token = os.environ.get("SF_SECURITY_TOKEN")

    missing = [
        name
        for name, value in [
            ("SF_USERNAME", username),
            ("SF_PASSWORD", password),
            ("SF_SECURITY_TOKEN", token),
        ]
        if not value
    ]
    if missing:
        raise SalesforceConfigError(
            f"Missing from .env: {', '.join(missing)}. "
            "Copy the SF_ block from .env.example and fill it in. "
            "Alternatively set SF_ACCESS_TOKEN and SF_INSTANCE_URL to skip "
            "password auth entirely (see get_connection above)."
        )

    return Salesforce(
        username=username,
        password=password,
        security_token=token,
        domain=DOMAIN,
    )


def strip_html(raw: str | None) -> str:
    """Turn Salesforce rich text into plain text.

    Knowledge bodies are HTML in a real org but plain text in our mock data.
    Without this, our tokenizer would happily index "div", "strong" and "br"
    as if they were meaningful words, and every article would share them --
    which is exactly the kind of noise IDF then has to work around.

    Block-level tags become newlines so the article's structure survives.
    """
    if not raw:
        return ""

    text = raw

    # Merge adjacent lists BEFORE numbering. Rich-text editors (and our own
    # CSV importer) often emit one <ol> per item, which would otherwise number
    # every step "1." instead of counting up.
    text = re.sub(r"(?is)</ol>\s*<ol[^>]*>", "", text)
    text = re.sub(r"(?is)</ul>\s*<ul[^>]*>", "", text)

    def _ordered(match: "re.Match[str]") -> str:
        items = re.findall(r"(?is)<li[^>]*>(.*?)</li>", match.group(1))
        return "\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(items, 1)) + "\n"

    def _bulleted(match: "re.Match[str]") -> str:
        items = re.findall(r"(?is)<li[^>]*>(.*?)</li>", match.group(1))
        return "\n" + "\n".join(f"- {t}" for t in items) + "\n"

    # Numbered steps stay numbered. The agent quotes these back to customers as
    # "check step 1 first", so losing the ordinals loses real meaning.
    text = re.sub(r"(?is)<ol[^>]*>(.*?)</ol>", _ordered, text)
    text = re.sub(r"(?is)<ul[^>]*>(.*?)</ul>", _bulleted, text)

    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)      # drop every remaining tag
    text = html.unescape(text)               # &amp; -> &, &nbsp; -> space
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _nested(record: dict, relationship: str, field: str) -> str:
    """Pull Contact.Name / Account.Name out of a SOQL result safely.

    Relationship fields come back nested -- {"Contact": {"Name": "..."}} -- and
    the whole nested object is None when the lookup is empty, which is common
    on Cases with no Contact.
    """
    related = record.get(relationship)
    return (related or {}).get(field) or ""


def _normalise_case(record: dict) -> dict:
    """Reshape a SOQL Case row into the same dict our mock data uses."""
    return {
        "Id": record.get("Id", ""),
        "CaseNumber": record.get("CaseNumber", ""),
        "Subject": record.get("Subject") or "",
        "Description": record.get("Description") or "",
        "Status": record.get("Status") or "",
        "Priority": record.get("Priority") or "",
        "Origin": record.get("Origin") or "",
        "Type": record.get("Type") or "",
        "Reason": record.get("Reason") or "",
        "ContactName": _nested(record, "Contact", "Name"),
        "ContactEmail": _nested(record, "Contact", "Email"),
        "AccountName": _nested(record, "Account", "Name"),
        "CreatedDate": record.get("CreatedDate", ""),
        "IsClosed": record.get("IsClosed", False),
    }


CASE_FIELDS = (
    "Id, CaseNumber, Subject, Description, Status, Priority, Origin, Type, "
    "Reason, Contact.Name, Contact.Email, Account.Name, CreatedDate, IsClosed"
)


def fetch_cases(limit: int = 50, open_only: bool = True) -> list[dict]:
    """Query Cases from the org, newest first."""
    sf = get_connection()
    where = "WHERE IsClosed = false " if open_only else ""
    soql = (
        f"SELECT {CASE_FIELDS} FROM Case {where}"
        f"ORDER BY CreatedDate DESC LIMIT {int(limit)}"
    )
    return [_normalise_case(r) for r in sf.query_all(soql)["records"]]


def fetch_case(case_number: str) -> dict | None:
    """Query one Case by CaseNumber, or None if it does not exist."""
    sf = get_connection()
    # Escaping single quotes matters: a stray quote in user input would
    # otherwise break the query. This is SOQL injection, same idea as SQL.
    safe = case_number.replace("'", r"\'")
    soql = f"SELECT {CASE_FIELDS} FROM Case WHERE CaseNumber = '{safe}' LIMIT 1"
    records = sf.query_all(soql)["records"]
    return _normalise_case(records[0]) if records else None


def fetch_articles(limit: int = 200) -> list[dict]:
    """Query published Knowledge Articles.

    Two filters do a lot of work here:
      PublishStatus = 'Online'  -- Draft and Archived versions are invisible to
                                   customers, so they must not reach the agent.
                                   Forgetting this is the classic first-time
                                   "why is my query empty" moment: newly created
                                   articles are Drafts until you publish them.
      Language = 'en_US'        -- Knowledge is translatable, and without this
                                   you get one row per language per article.
    """
    sf = get_connection()
    soql = (
        f"SELECT Id, ArticleNumber, Title, Summary, UrlName, PublishStatus, "
        f"Language, VersionNumber, LastPublishedDate, {BODY_FIELD} "
        f"FROM Knowledge__kav "
        f"WHERE PublishStatus = 'Online' AND Language = 'en_US' "
        f"LIMIT {int(limit)}"
    )
    records = sf.query_all(soql)["records"]

    articles = []
    for record in records:
        articles.append(
            {
                "Id": record.get("Id", ""),
                "ArticleNumber": record.get("ArticleNumber", ""),
                "Title": record.get("Title") or "",
                "Summary": strip_html(record.get("Summary")),
                "UrlName": record.get("UrlName") or "",
                # Normalised to "Answer__c" whatever the org calls it, so
                # retrieval.py and tools.py never need to know.
                "Answer__c": strip_html(record.get(BODY_FIELD)),
                "PublishStatus": record.get("PublishStatus", ""),
                "Language": record.get("Language", ""),
                "VersionNumber": record.get("VersionNumber", 0),
                "LastPublishedDate": record.get("LastPublishedDate", ""),
            }
        )
    return articles


# Salesforce hard-limits CommentBody. Exceeding it returns STRING_TOO_LONG.
COMMENT_MAX_CHARS = 4000


def create_case_comment(case_id: str, body: str, is_published: bool = False) -> dict:
    """Write a comment onto a Case. Returns {"id": ..., "truncated": bool}.

    is_published defaults to FALSE on purpose. A published CaseComment is
    visible to the customer in the portal, and everything this agent writes is
    a draft awaiting human review -- publishing it automatically would be
    exactly the failure mode the whole design avoids.
    """
    sf = get_connection()

    truncated = len(body) > COMMENT_MAX_CHARS
    if truncated:
        # Cut at a word boundary and say so, rather than stopping mid-sentence
        # and leaving a reviewer wondering whether the model ran out of ideas.
        keep = body[: COMMENT_MAX_CHARS - 40].rsplit(" ", 1)[0]
        body = keep + "\n\n[truncated at 4000 characters]"

    result = sf.CaseComment.create(
        {"ParentId": case_id, "CommentBody": body, "IsPublished": is_published}
    )
    return {"id": result["id"], "truncated": truncated}


def fetch_case_comments(case_id: str, limit: int = 10) -> list[dict]:
    """Read comments back off a Case, newest first -- used to verify writes."""
    sf = get_connection()
    safe = case_id.replace("'", r"\'")
    soql = (
        "SELECT Id, CommentBody, IsPublished, CreatedDate "
        f"FROM CaseComment WHERE ParentId = '{safe}' "
        f"ORDER BY CreatedDate DESC LIMIT {int(limit)}"
    )
    return sf.query_all(soql)["records"]
