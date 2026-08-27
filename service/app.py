"""
Phase 1: an HTTP wrapper around the agent, so Salesforce can call it.

This is a THIN shell. It adds no intelligence -- it authenticates the caller,
runs the agent we already built, and reports what happened in a shape Apex can
parse. Everything in src/ is imported unchanged.

Run it:
    source .venv/bin/activate
    export COPILOT_SHARED_SECRET='pick-something-long'
    DATA_SOURCE=salesforce uvicorn service.app:app --reload

Then:
    curl -X POST localhost:8000/draft \
      -H 'Content-Type: application/json' \
      -H "X-Copilot-Secret: $COPILOT_SHARED_SECRET" \
      -d '{"case_number": "00001026"}'
"""

import os
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

# src/ is a plain folder of modules, not an installed package, so put it on the
# import path before importing from it.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import agent as agent_module  # noqa: E402
import data_store  # noqa: E402

load_dotenv()

# The tunnel URL in Phase 3 is public. Without this check, anyone who finds it
# can spend your Anthropic credit. Required -- the service refuses to start
# without it rather than defaulting to something insecure.
SHARED_SECRET = os.environ.get("COPILOT_SHARED_SECRET", "")

# Built once at startup, not per request. Constructing the agent parses tool
# schemas and builds a graph; doing that on every call would add latency for
# no reason.
AGENT = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global AGENT
    if not SHARED_SECRET:
        raise RuntimeError(
            "COPILOT_SHARED_SECRET is not set. Refusing to start an unauthenticated "
            "service that spends money. Set it in .env or the environment."
        )
    # Only /draft uses this shared agent. /chat builds its own per request,
    # because its system prompt carries the specific case.
    AGENT = agent_module.build_agent()
    yield


app = FastAPI(
    title="sf-case-copilot",
    description="Drafts Salesforce Case resolutions grounded in Knowledge Articles.",
    version="1.0.0",
    lifespan=lifespan,
)


def require_secret(supplied: str | None) -> None:
    """Reject callers without the shared secret.

    compare_digest rather than == so the comparison takes the same time whether
    the secret is wrong at the first character or the last. Overkill here, but
    it is the habit you want, and an interviewer may notice.
    """
    if not supplied or not secrets.compare_digest(supplied, SHARED_SECRET):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Copilot-Secret.")


class DraftRequest(BaseModel):
    case_number: str = Field(..., examples=["00001026"], max_length=30)


class DraftResponse(BaseModel):
    case_number: str
    drafted: bool          # False when the agent declined -- not an error
    draft: str | None
    comment_id: str | None
    summary: str           # the agent's own explanation, for the LWC to show
    tools_called: list[str]


@app.get("/healthz")
def healthz() -> dict:
    """Pure liveness. Touches nothing external.

    This is what Render's health check points at. /health talks to Salesforce,
    and if the token expires Render would read that as a dead app and restart
    it in a loop -- restarting fixes nothing, because the token is still
    expired. Liveness ("is the process up") and diagnostics ("is everything
    it depends on working") are different questions and need different URLs.
    """
    return {"ok": True}


@app.get("/health")
def health() -> dict:
    """Liveness plus a real check that Salesforce is reachable.

    Used by Render and by you, when something has stopped working and you need
    to know which half is broken.
    """
    source = data_store.DATA_SOURCE
    salesforce_ok = None

    if data_store.using_salesforce():
        try:
            data_store.list_articles()
            salesforce_ok = True
        except Exception:
            salesforce_ok = False

    return {"ok": True, "data_source": source, "salesforce": salesforce_ok}


@app.post("/draft", response_model=DraftResponse)
def draft(request: DraftRequest, x_copilot_secret: str = Header(default=None)) -> DraftResponse:
    """Run the agent against one Case and report what it did.

    Note that a REFUSAL is a success, not an error: when the knowledge base does
    not cover the case, the agent declines to draft and we return 200 with
    drafted=false. The LWC shows that differently from a failure, because it
    means something different -- the system worked correctly and had nothing to
    say.
    """
    require_secret(x_copilot_secret)

    case_number = request.case_number.strip()
    if not data_store.get_case(case_number):
        raise HTTPException(status_code=404, detail=f"No case found with number {case_number}.")

    # Forget any draft this process wrote for this case in an EARLIER request,
    # so a second button click leaves a new comment rather than silently
    # overwriting the one a colleague may be reading. Within a single run the
    # agent still replaces its own re-drafts -- see data_store.save_draft.
    data_store.forget_draft(case_number)

    try:
        result = agent_module.run(AGENT, f"Draft a resolution for case {case_number}.")
    except Exception as exc:
        # Anything from the model or the org. Give the caller the type and
        # message -- the LWC surfaces it, and a blank failure helps nobody.
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

    messages = result["messages"]

    tools_called = [
        call["name"]
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    ]

    finals = [
        m.text for m in messages
        if isinstance(m, AIMessage) and not m.tool_calls and m.text.strip()
    ]
    summary = finals[-1] if finals else ""

    # forget_draft() cleared this above, so anything here was written by THIS run.
    after = data_store.saved_drafts().get(case_number)
    drafted = after is not None

    return DraftResponse(
        case_number=case_number,
        drafted=drafted,
        draft=after["text"] if drafted else None,
        comment_id=after["comment_id"] if drafted else None,
        summary=summary,
        tools_called=tools_called,
    )


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    case_id: str = Field(..., max_length=20)
    # The FULL conversation so far, oldest first, excluding the new message.
    # The client owns this. The service keeps nothing between requests, which
    # is what lets it restart, sleep on a free tier, or run on several
    # instances without dropping anyone's conversation.
    history: list[ChatMessage] = Field(default_factory=list)
    message: str = Field(..., max_length=4000)


class ChatResponse(BaseModel):
    reply: str
    tools_called: list[str]


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, x_copilot_secret: str = Header(default=None)) -> ChatResponse:
    """One turn of a conversation about one Case.

    Stateless by design: everything the agent needs arrives in the request. The
    case details go into the system prompt (so no tool call is wasted looking up
    the record the LWC is already sitting on), and `history` is replayed as the
    conversation so far.

    The agent here is READ ONLY. It proposes drafts in the conversation; the
    human commits them with Save to Case, and Apex does that write.
    """
    require_secret(x_copilot_secret)

    case = data_store.get_case_by_id(request.case_id.strip())
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case found with Id {request.case_id}.")

    # Replay the client's history, then add the new message.
    messages: list = [
        HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
        for m in request.history
    ]
    messages.append(HumanMessage(content=request.message))

    agent = agent_module.build_chat_agent(case)

    try:
        result = agent.invoke({"messages": messages})
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

    produced = result["messages"][len(messages):]

    tools_called = [
        call["name"] for m in produced if isinstance(m, AIMessage) for call in m.tool_calls
    ]
    finals = [
        m.text for m in produced
        if isinstance(m, AIMessage) and not m.tool_calls and m.text.strip()
    ]

    return ChatResponse(reply=finals[-1] if finals else "", tools_called=tools_called)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
