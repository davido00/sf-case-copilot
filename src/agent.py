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

from tools import ALL_TOOLS

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
4. Call draft_resolution to save it against the case.

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


def build_agent():
    """Assemble the agent: a model, a set of tools, and instructions.

    Returns a graph object with the same `.invoke()` you have used since
    Step 2 -- the uniform interface again.
    """
    llm = ChatAnthropic(model=MODEL, max_tokens=16000)
    return create_agent(model=llm, tools=ALL_TOOLS, system_prompt=SYSTEM_PROMPT)


def run(agent, user_request: str) -> dict:
    """Run the agent once and return its full final state.

    The result contains `messages` -- the ENTIRE conversation, including every
    tool call and tool result. That list is the loop's own audit trail, which
    is what step5_agent.py prints.
    """
    return agent.invoke({"messages": [{"role": "user", "content": user_request}]})
