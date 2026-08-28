# sf-case-copilot

A chat panel on the Salesforce Case record page, backed by a hand-built
tool-calling LLM agent. It reads the Case, searches the Knowledge Base, and
drafts a resolution grounded in what it retrieves. The support agent decides what
to keep and clicks **Save to Case** — nothing reaches the record on its own.

Running against a real Salesforce org, end to end. Not a mock, not a video.

**This is deliberately the raw, hand-built version.** It is not how I would
recommend shipping this to a customer. [Why I built it this way](#why-i-built-this-the-hard-way).

---

## What it does

In the org — the LWC on a Case record page:

```
you>  What should I check first?
      [9.7s · searched the knowledge base]
      Per KB 000001003, start with Login History (Setup > Identity > Login
      History). "Your login attempt has failed" is deliberately generic — the
      Status column gives the real reason…

you>  Now write that as a reply I can send the customer.
      [11.4s · searched the knowledge base]
      Subject: Re: Cannot log in after password reset …

you>  Shorter, and drop the numbered list.
      [7.0s · no tools]                       ← revised from context alone
```

Then **Save to Case** writes the chosen reply to `AI_Draft_Resolution__c`.

## The behaviour I care most about

Given a Case the Knowledge Base does not cover, it refuses:

```
[step 2] search_knowledge_articles('electrical wiring installation GC5060 generator')
      -> No relevant knowledge articles found.
[step 3] search_knowledge_articles('wiring requirements voltage connection setup')
      -> No relevant knowledge articles found.

SAVED DRAFTS: (none)
comments on record: 0
```

It searched twice — narrowing, then broadening — then declined to draft and
recommended escalation. **Nothing was written to Salesforce.** A support tool that
invents plausible troubleshooting steps from an irrelevant article is worse than
no tool at all, so this is the case I test first.

That case is one of Trailhead's stock samples. I didn't write it, which is what
makes it a fair test.

## Why I built this the hard way

If a customer asked me how to ship this, the answer would not be a Python
service. It would be **Agentforce** for the agent and its actions, grounded on
**Data Cloud / Data 360** for unified, harmonised data and retrieval. That is the
supported, governed, upgradeable path, and it is what I would recommend.

I built the raw version first on purpose — to understand what those products are
abstracting away. Every piece here has a platform equivalent:

| What I hand-built | What the platform provides |
|---|---|
| `agent.py` — the tool-calling loop | Agentforce agent + its reasoning engine |
| `tools.py` — the tool definitions | Agentforce Topics and Actions |
| The system prompt in `agent.py` | Prompt Builder templates |
| `retrieval.py` — IDF keyword scoring | Data Cloud retrievers / vector search |
| `data_store.py` — the mock/live seam | Data Cloud's unified data model |
| `sf_client.py` — SOQL and auth plumbing | Zero-copy ingestion, Named Credentials |
| `CaseCopilotService.cls` — the callout | An Agentforce Action |
| `caseCopilot` LWC — the chat surface | The Agentforce panel, for free |
| *nothing* | Einstein Trust Layer — masking, audit, toxicity gating |

That last row is the honest one. My version has no PII masking, no audit trail,
and no guardrails beyond a system prompt — precisely the kind of thing you stop
taking for granted once you have tried to build it yourself.

Writing the retrieval scoring by hand is what made "grounding" concrete rather
than a slide. Writing the tool loop is what made it obvious that tool
descriptions are prompt engineering. I would rather configure Agentforce knowing
that than knowing only which buttons to click.

## Architecture

```
Case record page
  │
  ├─ caseCopilot (LWC)            owns the conversation; sends it in full each turn
  │        │  @AuraEnabled
  │        ▼
  ├─ CaseCopilotService (Apex)    the callout, and the only write in the flow
  │        │  callout:Case_Copilot        ← Named Credential holds URL + secret
  │        ▼
  └─ FastAPI on Render            POST /chat {case_id, history, message}
           │
           ▼
        agent.py                  create_agent() runs the tool loop
           │
        tools.py                  read-only in chat; docstrings ARE the prompt
           │
     ┌─────┴──────────┐
 retrieval.py    data_store.py    ← the seam
 keyword + IDF        │
                ┌─────┴───────┐
        sample_cases.json   sf_client.py
        (DATA_SOURCE=mock)  (DATA_SOURCE=salesforce)
```

`data_store.py` is the only module that knows where data comes from. `sf_client.py`
normalises SOQL rows into exactly the shape the JSON uses, so switching between
mock data and a live org is one environment variable and touches nothing else —
including the write path.

That paid off twice. The whole agent was built and debugged offline for free, then
pointed at a real org without changing a line of `retrieval.py`, `tools.py` or
`agent.py`. Then the HTTP service wrapped all of it without changing them either.

## Decisions worth defending

**The agent cannot write to Salesforce.** In chat it gets read-only tools. It
proposes; a person clicks Save; Apex performs the single write. An agent that
cannot write cannot write the wrong thing.

**Keyword retrieval with IDF weighting, not embeddings.** Words appearing in every
article score zero; rare words score high. 10/10 on the mock ground truth, 4/4
against the live org. A vector database would be complexity I could not yet
justify from evidence — and I can now describe exactly which failure would
justify it.

**The relevance threshold was measured, not guessed.** `MIN_SCORE = 9.0` comes
from a sweep: the best false match scores 5.7, the weakest true match 11.9.
Several values score perfectly; 9.0 sits between them with margin on both sides
rather than 0.3 above a known false positive. It held on live data without
retuning.

**Tools return sentences, not exceptions.** `get_case("99999999")` returns
`"No case found with number 99999999."` The model reads that and recovers. A
raised exception kills the agent loop.

**Chat is stateless; the client owns the history.** The LWC sends the whole
conversation every turn and the service keeps nothing. That is what lets it
restart, sleep on a free tier, or run on several instances without dropping
anyone mid-conversation.

**55-second timeout, two attempts — not 120 seconds and one.** Apex allows 120s
of callout time per *transaction*, not per call. Since the agent answers in 8–25s,
two shorter attempts cover more failure modes than one long one. The retry fires
only on 502/503/504, because a waking free-tier instance answers with a gateway
error rather than merely being slow. A 401 would fail identically twice.

**Errors use `CopilotException`, not `AuraHandledException`.** The latter's
`setMessage()` is only legal in a VisualForce/Aura context — from Execute
Anonymous it throws `LimitException` and hides the real problem. It did exactly
that, masking a live HTTP failure while pretending to report it. Now the logic
throws a plain exception and only the thin `@AuraEnabled` wrappers convert it, so
the same code is debuggable from anonymous Apex, from tests, and from the UI.

## What running it taught me that reading it wouldn't

Three bugs that were invisible in the code and obvious in the output:

**The agent left a trail of drafts.** It sometimes re-drafts, and
`draft_resolution` created a *new* CaseComment each time — one run left four
drafts on one Case. It now updates the comment it already wrote within a run.

**I built a self-critique loop by accident.** The tool returned the draft's word
count, sitting next to a prompt rule saying "under 250 words". The model chased
the target — four re-drafts, 51.8s instead of 22.1s, for a marginally different
draft. Removing the number from the tool's success message fixed it. **Don't put
metrics in a tool response; the model will optimise against them.**

**Case details in the system prompt beat a tool call.** The LWC already knows
which record it is on, so making the model call `get_case` to look it up was pure
latency. Moving the Case into the prompt cut the first turn from 25s to 9.7s.

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Anthropic key; Salesforce creds optional
```

**Offline and free — no Salesforce, no deployment:**

```bash
python src/step4_retrieval.py     # retrieval scored against ground truth
python src/step5_agent.py         # full agent run, tool trace printed
python src/chat.py                # interactive, multi-turn
```

**Against a real org:**

```bash
DATA_SOURCE=salesforce python src/step6_salesforce.py   # connection check, no LLM calls
DATA_SOURCE=salesforce python src/chat.py
```

**The HTTP service:**

```bash
DATA_SOURCE=salesforce uvicorn service.app:app --port 8000
python service/try_chat.py        # terminal client for POST /chat
```

`try_chat.py` reads `COPILOT_URL`, so the same client tests local or deployed. It
is also the reference implementation for the LWC — keep a list of
`{role, content}`, send it all each turn, append the reply. That is the whole
protocol, and it is where to look first when the component misbehaves.

**In the org:**

```bash
sf project deploy start -d force-app -o <your-org>
sf apex run test -o <your-org> -l RunSpecifiedTests -t CaseCopilotServiceTest
```

Then add the **Case Copilot** component to the Case Lightning page. Setup needs a
Named Credential (`Case_Copilot`) pointing at the service with the shared secret
as a custom header, and an `AI_Draft_Resolution__c` Long Text Area on Case.

The `stepN_*.py` files are deliberate teaching artifacts — each independently
runnable, from a raw API call with no framework through to the full agent.
`CLAUDE.md` is the build log.

## Honest limitations

- **The retrieval score is flattering.** I wrote the mock cases *and* the
  articles, so their vocabulary overlaps more than real data would. The live test
  used Trailhead sample cases I did not write and they correctly returned
  nothing — but that tests rejection, not matching. A real Knowledge base, where
  customers describe symptoms and authors describe causes, will score worse.
- **No streaming.** Apex HTTP callouts are request/response, so tokens cannot
  stream through Apex into an LWC. Streaming would mean the browser calling the
  service directly, which costs CSP/CORS configuration and a new short-lived-token
  auth mechanism. A spinner over 8–25s is the trade I took.
- **Synchronous, against a 120s ceiling.** It works, but the right answer is
  event-driven: return `202`, do the work in the background, publish a Platform
  Event, update the panel via `empApi`. Known, not done.
- **Word limits are suggestions.** The prompt says "under 250 words"; a draft came
  out at 293. Prompt rules are not constraints. A hard limit needs code.
- **SOAP `login()` is on borrowed time.** This deployment uses username/password/
  security token, which does not expire — but Salesforce retires the endpoint in
  Summer '27. `sf_client.py` already prefers an OAuth access token when one is
  configured; a Connected App with the JWT bearer flow is the durable answer.
- **Tests are uneven.** 12 Apex tests cover the callout and the write, including
  the retry and the failure paths. The Python side has none — verification there
  is the runnable step scripts and the live smoke test.
- **Free tier sleeps.** Render idles out after ~15 minutes; the first call after
  that takes ~40s. The retry exists because a waking instance returns an error
  rather than just being slow.

## Stack

**Agent** Python 3.11 · `anthropic` · LangChain 1.x (`create_agent`, LangGraph) ·
Claude Opus 5
**Service** FastAPI · `simple-salesforce` · Render
**Salesforce** Apex · Lightning Web Components · Named Credentials · SFDX
