"""
Step 2: the exact same call from Step 1, but through LangChain.

Same case, same system prompt, same model. Only the plumbing changes. Run this
next to step1_raw_claude.py and the point of the framework should come into
focus -- for ONE call it buys you almost nothing, which is worth seeing
honestly before we lean on it in Step 5.

Run it:
    source .venv/bin/activate
    python src/step2_langchain.py
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

# Reusing Step 1's inputs so the comparison is honest -- identical case,
# identical system prompt. Python finds this because both files live in src/,
# and the directory of the script you run is always on the import path.
# (Importing it also runs step 1's load_dotenv(), so the key is loaded.)
from step1_raw_claude import MODEL, SAMPLE_CASE, SYSTEM_PROMPT, build_user_prompt


# ---------------------------------------------------------------------------
# The model object.
#
# In Step 1 we made an `anthropic.Anthropic()` client and passed `model` and
# `max_tokens` on every single call. Here those settings live ON the object.
# That is the first real difference: configuration is bound once, up front.
#
# `ChatAnthropic` is a "chat model" -- LangChain's provider-neutral interface.
# Swapping to another provider means changing this one line; everything
# downstream (messages, prompts, chains, tools) stays identical.
# ---------------------------------------------------------------------------
llm = ChatAnthropic(model=MODEL, max_tokens=16000)


def part_a_direct_translation() -> None:
    """The 1:1 translation of Step 1. Same call, LangChain's vocabulary."""
    print("=" * 70)
    print("PART A -- the same call, translated")
    print("=" * 70)

    # Step 1 sent:  system="..."  +  messages=[{"role": "user", "content": "..."}]
    # LangChain uses typed objects instead of dicts with a "role" string.
    # SystemMessage == the `system` parameter. HumanMessage == role "user".
    # There is also AIMessage, which == role "assistant" (Claude's own replies).
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=build_user_prompt(SAMPLE_CASE)),
    ]

    # `.invoke()` is LangChain's universal "run this once" verb. Every LangChain
    # component has it -- models, prompts, parsers, chains, agents. Learning it
    # once means you can run any of them.
    reply = llm.invoke(messages)

    # `reply` is an AIMessage. Two ways to get the text out, and the difference
    # matters:
    #
    #   reply.content -- the RAW blocks. Usually a string, but when Claude
    #                    thinks before answering (adaptive thinking is on by
    #                    default on claude-opus-5) it is a LIST of block dicts,
    #                    exactly like response.content was in Step 1.
    #   reply.text    -- the text blocks, concatenated into a plain string.
    #
    # Use `.text` unless you specifically need the blocks. This is the Step 1
    # `for block in response.content: if block.type == "text"` loop, done for us.
    print(reply.text)

    print()
    print("-" * 70)
    print(f"content type: {type(reply.content).__name__}")

    # LangChain normalises token usage into the same shape for every provider,
    # so cost tracking code doesn't care which model you used.
    usage = reply.usage_metadata
    print(f"input tokens:  {usage['input_tokens']}")
    print(f"output tokens: {usage['output_tokens']}")


# ---------------------------------------------------------------------------
# A second case, so Part B has something to fan out over.
# ---------------------------------------------------------------------------
SECOND_CASE = {
    "CaseNumber": "00001043",
    "Subject": "Report shows no rows for records the user can see in list view",
    "Description": (
        "A sales user can open Opportunity records directly and sees them in a "
        "list view, but a custom report of the same object returns zero rows "
        "for them. Other users on the same profile see the expected rows."
    ),
    "Priority": "Medium",
    "Status": "Working",
}

# The Step 1 f-string, rewritten as a TEMPLATE. Note `{case_number}` is not an
# f-string -- there is no `f` prefix. The braces are placeholders that LangChain
# fills in later, which is what makes this object reusable.
HUMAN_TEMPLATE = """Draft a resolution for this Salesforce support case.

Case Number: {case_number}
Priority:    {priority}
Status:      {status}
Subject:     {subject}

Description:
{description}"""


def part_b_the_actual_payoff() -> None:
    """Prompt templates + chains -- the part that isn't just renaming things."""
    print()
    print("=" * 70)
    print("PART B -- what LangChain is actually for")
    print("=" * 70)

    # A prompt template is a reusable, inspectable object rather than a function
    # that returns a string. It knows which variables it needs.
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", HUMAN_TEMPLATE),
        ]
    )
    print(f"template expects: {sorted(prompt.input_variables)}\n")

    # THE CHAIN. `|` is Python's pipe operator, which LangChain overloads to
    # mean "feed the output of the left into the right":
    #
    #     dict -> prompt (fills the template) -> llm (calls Claude)
    #          -> StrOutputParser (pulls the text out of the AIMessage)
    #
    # The result is itself a runnable object with the same `.invoke()` you saw
    # in Part A. That uniformity is the whole design: everything composes
    # because everything speaks the same interface.
    chain = prompt | llm | StrOutputParser()

    cases = [SAMPLE_CASE, SECOND_CASE]
    inputs = [
        {
            "case_number": c["CaseNumber"],
            "priority": c["Priority"],
            "status": c["Status"],
            "subject": c["Subject"],
            "description": c["Description"],
        }
        for c in cases
    ]

    # `.batch()` runs them CONCURRENTLY -- two cases, roughly the time of one.
    # We wrote no threading code. Doing this by hand in Step 1 would have meant
    # managing a thread pool ourselves.
    drafts = chain.batch(inputs)

    for case, draft in zip(cases, drafts):
        print("-" * 70)
        print(f"Case {case['CaseNumber']} -- {case['Subject']}")
        print("-" * 70)
        # StrOutputParser already gave us a plain string, so no block handling.
        print(draft)
        print()


if __name__ == "__main__":
    part_a_direct_translation()
    part_b_the_actual_payoff()
