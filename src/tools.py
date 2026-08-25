"""
Step 5: the tools the agent is allowed to call.

A "tool" is just a Python function that Claude is allowed to ask us to run.
The model never runs anything itself -- it replies "please call
search_knowledge_articles with query='login failure'", our code runs the real
function, and we hand the result back. The model decides WHAT to call; our
code stays in control of what actually happens.

The single most important thing on this page is the DOCSTRINGS. They are not
comments for you -- they are sent to Claude verbatim, and they are the only
thing it has to decide which tool fits. A vague docstring produces an agent
that calls the wrong tool. Treat them as part of the prompt, because they are.
"""

from langchain_core.tools import tool

import data_store
import retrieval

# Where drafts go for now. In Step 7 this is replaced by a write back to the
# Case record in Salesforce; keeping it in a plain dict means we can build and
# debug the whole agent without touching a real org.
DRAFTS: dict[str, str] = {}


@tool
def get_case(case_number: str) -> str:
    """Look up a single Salesforce Support Case by its case number.

    Use this first, to read the customer's reported problem before doing
    anything else. The case number is an 8-digit string such as "00001042".

    Returns the case's subject, description, priority, status and contact
    details, or a message saying the case does not exist.
    """
    case = data_store.get_case(case_number)
    if case is None:
        # Returning a sentence rather than raising is deliberate. The model
        # reads this and can recover -- ask the user for a valid number,
        # rather than the whole loop dying on an exception.
        return f"No case found with number {case_number}."

    return (
        f"Case Number: {case['CaseNumber']}\n"
        f"Subject: {case['Subject']}\n"
        f"Status: {case['Status']}\n"
        f"Priority: {case['Priority']}\n"
        f"Type: {case['Type']} / {case['Reason']}\n"
        f"Account: {case['AccountName']}\n"
        f"Contact: {case['ContactName']} <{case['ContactEmail']}>\n\n"
        f"Description:\n{case['Description']}"
    )


@tool
def search_knowledge_articles(query: str) -> str:
    """Search the Knowledge Base for articles relevant to a support problem.

    Pass a description of the customer's problem -- typically the case subject
    and description, or the key symptoms and any error messages. Do not pass a
    case number; this searches article text, not case records.

    Returns the full text of the matching articles, best match first, or a
    message saying nothing relevant was found. If nothing is found, say so in
    your reply rather than answering from general knowledge.
    """
    articles = data_store.list_articles()
    results = retrieval.search_articles(query, articles)

    if not results:
        # This is the case 00001051 path. The model must be told plainly that
        # the knowledge base has nothing, or it will fill the gap itself.
        return (
            "No relevant knowledge articles found for that query. "
            "The knowledge base does not cover this problem."
        )

    chunks = []
    for article, score in results:
        chunks.append(
            f"--- Article {article['ArticleNumber']} "
            f"(relevance score {score:.1f}) ---\n"
            f"Title: {article['Title']}\n"
            f"Summary: {article['Summary']}\n\n"
            f"{article['Answer__c']}"
        )
    return "\n\n".join(chunks)


@tool
def draft_resolution(case_number: str, draft_text: str) -> str:
    """Save a drafted resolution reply against a Case.

    Call this once you have written the reply, passing the case number and the
    full draft text. Only call it after you have read the case and searched the
    knowledge base.

    The draft is saved for a human support agent to review before it is sent to
    the customer -- it is never sent automatically.
    """
    if data_store.get_case(case_number) is None:
        return f"Cannot save a draft: no case found with number {case_number}."

    DRAFTS[case_number] = draft_text
    words = len(draft_text.split())
    return f"Draft saved against case {case_number} ({words} words), pending agent review."


# The list we hand to the agent. Order does not matter to the model -- it picks
# by docstring, not by position.
ALL_TOOLS = [get_case, search_knowledge_articles, draft_resolution]
