"""
Step 1: A raw Claude API call. No LangChain, no agent, no tools.

The goal is to see the whole request/response cycle with nothing hiding it:
we hand Claude some text, Claude hands text back. Everything we build later
(LangChain, retrieval, tools, the agent loop) is a wrapper around this call.

Run it:
    source .venv/bin/activate
    python src/step1_raw_claude.py
"""

import os
import sys

import anthropic
from dotenv import load_dotenv

# Reads the `.env` file in the repo root and puts its values into the
# process's environment variables. This is why the key never appears in code.
load_dotenv()

# The exact model string. Not a date-suffixed variant — this ID is complete as-is.
MODEL = "claude-opus-5"


# ---------------------------------------------------------------------------
# The input. In Step 3 this becomes real JSON; in Step 6 it comes from
# Salesforce. For now it's hardcoded so there's one moving part, not three.
# ---------------------------------------------------------------------------
SAMPLE_CASE = {
    "CaseNumber": "00001042",
    "Subject": "Cannot log in to Community portal after password reset",
    "Description": (
        "Customer reset their password via the 'Forgot Password' link on our "
        "Experience Cloud site. They received the reset email and set a new "
        "password, but logging in still returns 'Your login attempt has failed.' "
        "They have tried two different browsers. Account was created 3 weeks ago."
    ),
    "Priority": "High",
    "Status": "New",
}


# ---------------------------------------------------------------------------
# The system prompt: standing instructions that apply to the whole
# conversation. Think of it as configuration for the model's behaviour —
# its role, its tone, its output format. It is separate from the user's
# message, and the model treats it with more authority.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a Salesforce support engineer drafting a reply to a customer.

Write a resolution draft that:
- Opens by restating the problem so the customer knows they were understood.
- Gives concrete, numbered troubleshooting steps a support agent can follow.
- Names the specific Salesforce features or settings involved where relevant.
- Stays under 250 words and uses plain, non-condescending language.

This is a DRAFT for a human agent to review — never invent case history,
account details, or promises about timelines."""


def build_user_prompt(case: dict) -> str:
    """Turn a Case record (a dict) into the plain text we send to Claude.

    This is the humblest possible version of 'prompt engineering': formatting
    structured data into a string. When we add Knowledge Articles in Step 4,
    they get pasted in here too — that is literally what RAG is.
    """
    return f"""Draft a resolution for this Salesforce support case.

Case Number: {case['CaseNumber']}
Priority:    {case['Priority']}
Status:      {case['Status']}
Subject:     {case['Subject']}

Description:
{case['Description']}"""


def main() -> None:
    # Fail early with a useful message instead of a confusing SDK error.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit(
            "ANTHROPIC_API_KEY is not set.\n"
            "Copy .env.example to .env and put your key in it:\n"
            "    cp .env.example .env"
        )

    # The client is the object that knows how to talk to the API. It picks up
    # ANTHROPIC_API_KEY from the environment on its own — no need to pass it.
    client = anthropic.Anthropic()

    user_prompt = build_user_prompt(SAMPLE_CASE)

    print("=" * 70)
    print("SENDING TO CLAUDE")
    print("=" * 70)
    print(user_prompt)
    print()

    try:
        # THE CALL. Three things matter here:
        #
        #   model      — which Claude to use.
        #   max_tokens — a hard CEILING on the reply length. It is not a target
        #                and does not cost anything by itself; you only pay for
        #                tokens actually generated. Set it high enough that a
        #                normal answer is never cut off mid-sentence.
        #   messages   — the conversation, as a list. Each entry has a "role"
        #                ("user" or "assistant") and "content". The API is
        #                STATELESS: it remembers nothing between calls, so a
        #                multi-turn chat means resending the whole list each
        #                time. We'll rely on that in Step 5.
        #
        # `system` sits outside `messages` because it isn't part of the
        # conversation — it's the standing instruction set.
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )
    except anthropic.AuthenticationError:
        sys.exit("Your ANTHROPIC_API_KEY was rejected. Check the value in .env.")
    except anthropic.RateLimitError:
        sys.exit("Rate limited by the API. Wait a moment and try again.")
    except anthropic.APIConnectionError:
        sys.exit("Could not reach the API. Check your internet connection.")

    print("=" * 70)
    print("CLAUDE'S REPLY")
    print("=" * 70)

    # `response.content` is a LIST of blocks, not a string. A reply can contain
    # several kinds of block — plain text, the model's reasoning, requests to
    # call a tool (Step 5). So we check each block's `.type` before reading it.
    # This is the detail LangChain will hide from us in Step 2, and the same
    # detail we'll need back when we build the agent loop.
    for block in response.content:
        if block.type == "text":
            print(block.text)

    # Usage tells you what the call actually cost, in tokens.
    print()
    print("-" * 70)
    print(f"stop_reason:   {response.stop_reason}")
    print(f"input tokens:  {response.usage.input_tokens}")
    print(f"output tokens: {response.usage.output_tokens}")


if __name__ == "__main__":
    main()
