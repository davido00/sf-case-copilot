"""
Step 6: prove the Salesforce connection works, before trusting the agent to it.

Run this FIRST, on its own. It makes no Claude calls -- it only connects to the
org, runs the two queries the project depends on, and reports exactly what came
back. When something is wrong with the org setup, the error appears here in one
line instead of buried inside an agent loop.

Run it:
    source .venv/bin/activate
    DATA_SOURCE=salesforce python src/step6_salesforce.py
"""

import os
import re
import sys

import data_store


def main() -> None:
    print("=" * 78)
    print("SALESFORCE CONNECTION CHECK")
    print("=" * 78)

    if not data_store.using_salesforce():
        print(f"\nDATA_SOURCE is '{data_store.DATA_SOURCE}', so this would read the")
        print("mock JSON, not your org. Run it like this instead:\n")
        print("    DATA_SOURCE=salesforce python src/step6_salesforce.py\n")
        print("or set DATA_SOURCE=salesforce in your .env file.")
        sys.exit(1)

    import sf_client

    # --- connect ---------------------------------------------------------
    print(f"\nusername: {os.environ.get('SF_USERNAME')}")
    print(f"domain:   {sf_client.DOMAIN}")
    print(f"body field: {sf_client.BODY_FIELD}")
    print("\nconnecting...")

    try:
        sf = sf_client.get_connection()
    except sf_client.SalesforceConfigError as exc:
        sys.exit(f"\nConfiguration problem: {exc}")
    except Exception as exc:
        # simple-salesforce raises a few different auth errors; the message it
        # carries is usually the actually useful part.
        sys.exit(
            f"\nCould not log in: {type(exc).__name__}: {exc}\n\n"
            "Common causes:\n"
            "  - SOAP API login() is disabled (new orgs disable it by default):\n"
            "      Setup > Quick Find 'User Interface' > Enable SOAP API login()\n"
            "      or switch to SF_ACCESS_TOKEN + SF_INSTANCE_URL (see .env.example)\n"
            "  - security token is stale (reset it and paste the new one)\n"
            "  - password recently changed (the token changes with it)\n"
            "  - SF_DOMAIN should be 'test' for a sandbox\n"
            "  - the user lacks the 'API Enabled' permission"
        )

    print(f"connected. instance: {sf.sf_instance}")

    # --- cases -----------------------------------------------------------
    print()
    print("-" * 78)
    print("CASES")
    print("-" * 78)
    cases = data_store.list_cases()
    if not cases:
        print("  No open cases found. Create a few Cases in the org.")
    for case in cases[:10]:
        print(f"  {case['CaseNumber']:<10} {case['Priority']:<9} {case['Subject'][:48]}")
    print(f"\n  {len(cases)} open case(s) retrieved.")

    # --- articles --------------------------------------------------------
    print()
    print("-" * 78)
    print("KNOWLEDGE ARTICLES")
    print("-" * 78)
    try:
        articles = data_store.list_articles()
    except Exception as exc:
        sys.exit(
            f"\nArticle query failed: {type(exc).__name__}: {exc}\n\n"
            "Common causes:\n"
            "  - Lightning Knowledge is not enabled (Setup > Knowledge Settings)\n"
            "  - your user does not have the 'Knowledge User' checkbox ticked\n"
            f"  - the field '{sf_client.BODY_FIELD}' does not exist on Knowledge__kav\n"
            "    (set SF_KNOWLEDGE_BODY_FIELD in .env to whatever you called it)"
        )

    if not articles:
        print("  No PUBLISHED articles found.")
        print("  Articles start as Drafts -- they only appear here once published.")
        print("  Setup > Knowledge > find the article > Publish.")
    for article in articles:
        body_words = len(article["Answer__c"].split())
        print(f"  {article['ArticleNumber']:<12} {article['Title'][:44]}")
        print(f"  {'':<12} {body_words} words of body text after HTML stripping")

    # --- the thing most likely to be quietly broken ----------------------
    print()
    print("-" * 78)
    print("HTML STRIPPING CHECK")
    print("-" * 78)
    if articles:
        sample = articles[0]["Answer__c"]
        # Look for an actual tag, not a stray angle bracket -- article text
        # legitimately contains things like "Setup > Users".
        if re.search(r"<[a-zA-Z/][^>]*>", sample):
            print("  WARNING: article body still looks like it contains HTML tags.")
        print(f"  First 300 chars of {articles[0]['ArticleNumber']}:\n")
        print("   ", sample[:300].replace("\n", "\n    "))
    else:
        print("  (skipped -- no articles to check)")

    print()
    print("=" * 78)
    if cases and articles:
        print("Looks good. Try the agent against the org:")
        print("    DATA_SOURCE=salesforce python src/chat.py")
    else:
        print("Connection works, but the org is missing data (see above).")
    print("=" * 78)


if __name__ == "__main__":
    main()
