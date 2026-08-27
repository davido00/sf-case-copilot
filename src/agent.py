"""
Step 5: the agent.

Steps 1-4 were a fixed pipeline: WE decided to fetch the case, then retrieve
articles, then call the model. An agent inverts that. We hand Claude a set of
tools and a goal, and it decides which to call and in what order.

The loop underneath is simple, and it is worth being able to describe it:

    1. Send the conversation (plus the tool list) to Claude.
    2. Claude replies either with a final answer, or with "call this tool".
    3. If it asked for a tool, run it and append the result to the conversation.
    4. Go back to 1.

That is the whole thing. `create_agent` writes this loop for us -- it is the
reason we brought LangChain in at all.
"""

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic

from tools import ALL_TOOLS, READ_TOOLS

# Load .env here, in the module that actually builds the model. Step 2 got the
# key by accident -- it imported step1_raw_claude, which happened to call
# load_dotenv() at import time. Relying on that is how you end up with an
# "authentication failed" error the moment you stop importing the right file.
load_dotenv()

MODEL = "claude-opus-5"

# The agent's standing instructions. Compare this with Step 1's system prompt:
# that one described the OUTPUT we wanted. This one describes a PROCEDURE,
# because the model now has to decide what to do, not just what to write.
SYSTEM_PROMPT = """You are a Salesforce support engineer drafting case resolutions.

When given a case number, follow this procedure:

1. Call get_case to read the case.
2. Call search_knowledge_articles using the case's symptoms and any error
   messages as the query.
3. Write a resolution draft grounded in the article content you retrieved.
4. Call draft_resolution to save it against the case. Call it ONCE. Do not
   re-draft or call it again unless the tool reports an error.

Rules for the draft:
- Open by restating the problem so the customer knows they were understood.
- Give concrete, numbered troubleshooting steps.
- Base the steps on the retrieved articles. Cite the article number you used.
- Stay under 250 words, in plain, non-condescending language.
- Never invent case history, account details, or timeline promises.

If search_knowledge_articles finds nothing relevant, do NOT write a draft from
general knowledge. Instead, say clearly that the knowledge base does not cover
this problem and that the case should be escalated to a specialist. Do not call
draft_resolution in that situation."""


def build_agent(checkpointer=None):
    """Assemble the agent: a model, a set of tools, and instructions.

    Returns a graph object with the same `.invoke()` you have used since
    Step 2 -- the uniform interface again.

    Pass a CHECKPOINTER to give the agent memory. LangGraph then stores the
    message list per `thread_id` and reloads it on the next call, so a web
    client can hold a conversation without shipping the whole history back
    every turn. `chat.py` does the same job by hand with a Python list; this
    is the version that survives being behind an HTTP endpoint.
    """
    llm = ChatAnthropic(model=MODEL, max_tokens=16000)
    return create_agent(
        model=llm,
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


def run(agent, user_request: str, thread_id: str | None = None) -> dict:
    """Send one message to the agent and return its full final state.

    The result contains `messages` -- the ENTIRE conversation, including every
    tool call and tool result. That list is the loop's own audit trail, which
    is what step5_agent.py prints.

    With a `thread_id` (and an agent built with a checkpointer), earlier turns
    on that thread are loaded automatically, so you send only the NEW message.
    """
    config = {"configurable": {"thread_id": thread_id}} if thread_id else None
    return agent.invoke(
        {"messages": [{"role": "user", "content": user_request}]},
        config=config,
    )


# ---------------------------------------------------------------------------
# Chat mode (in-org build)
#
# Different job from the one-shot drafting agent above. Here a human is in the
# loop, so the agent converses instead of executing a fixed procedure, and it
# has NO write tools -- the person decides when to commit, and Apex does the
# writing. An agent that cannot write cannot write the wrong thing.
# ---------------------------------------------------------------------------

CHAT_SYSTEM_PROMPT = """You are a Salesforce support engineer helping a colleague
work on a support case. You are talking to the support agent, not to the customer.

The case you are working on:

{case_block}

How to work:
- You ALREADY have this case's details above. Never call get_case for it. Use
  get_case only if asked about some OTHER case by number.
- Search the Knowledge Base before proposing any troubleshooting steps, and base
  those steps on what you retrieve. Cite the article number you used.
- If the Knowledge Base has nothing relevant, say so plainly and recommend
  escalation. Do NOT fall back on general knowledge and present it as grounded.
- When asked for a customer reply, write the reply itself, ready to send.
- Keep answers tight. This is a working conversation, not a report.

You CANNOT write to Salesforce. You have read access only. When your colleague is
happy with a draft they will save it themselves using the Save to Case button, so
present drafts in the conversation and never claim to have saved anything."""


def case_block(case: dict) -> str:
    """Format a Case for the chat system prompt.

    Putting the case in the prompt rather than making the agent fetch it saves a
    tool call on every single conversation -- the LWC already knows which record
    it is on, so asking the model to go and look it up is wasted latency.
    """
    return (
        f"Case Number: {case['CaseNumber']}\n"
        f"Subject: {case['Subject']}\n"
        f"Status: {case['Status']} | Priority: {case['Priority']}\n"
        f"Type: {case['Type']} / {case['Reason']}\n"
        f"Account: {case['AccountName']}\n"
        f"Contact: {case['ContactName']} <{case['ContactEmail']}>\n\n"
        f"Description:\n{case['Description']}"
    )


def build_chat_agent(case: dict):
    """A read-only agent that already knows which case it is working on.

    Built per request -- it costs under 2ms, and it means the case details live
    in the system prompt rather than being re-fetched or carried in history.
    """
    llm = ChatAnthropic(model=MODEL, max_tokens=16000)
    return create_agent(
        model=llm,
        tools=READ_TOOLS,
        system_prompt=CHAT_SYSTEM_PROMPT.format(case_block=case_block(case)),
    )
