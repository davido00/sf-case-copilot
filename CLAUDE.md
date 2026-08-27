# sf-case-copilot

## What this is

A learning/portfolio project: a **LangChain agent that reads Salesforce Support Cases,
retrieves relevant Knowledge Articles, drafts a resolution with an LLM, and writes the
draft back to the Case record.**

Built as interview prep for a **Forward Deployed Engineer (FDE)** role at Salesforce
(Polish-speaking). The point is to demonstrate: LLM agent development, LangChain,
tool-calling, RAG, and Salesforce integration — from the perspective of an experienced
Salesforce developer who is new to Python and LLMs.

## Positioning — do not lose this framing

This is **deliberately the raw, hand-built version, not a recommended architecture.**
The enterprise answer is Agentforce for orchestration and actions, grounded on
Data Cloud / Data 360. The owner knows that; building it by hand first is the point.

This matters for how the project is presented. Describing this stack as the *right*
way to ship would read as a gap in Salesforce platform knowledge. Framing it as
"I built the raw version to understand what Agentforce abstracts away" reads as
senior instinct. **Never write copy that presents this as best-practice
architecture.** The README's "Why I built this the hard way" section — including
the hand-built → platform mapping table — carries that framing; keep it intact.

## Working style for this repo

The owner is an experienced Salesforce dev but **new to Python and LLM development**. So:

- Explain what each piece of code does in plain terms as it is written.
- Build **incrementally** — every step must end in something runnable.
- **Stop and check in** with the owner before starting the next step.
- Prefer readable, obvious code over clever code. Comments explain *why*, not *what*.

## Tech decisions

| Concern | Choice | Why |
|---|---|---|
| LLM | **Anthropic Claude** via the `anthropic` Python package | Owner's choice |
| Model ID | `claude-opus-5` | Current flagship; exact string, no date suffix |
| Framework | LangChain (`langchain-anthropic`), added in Step 2 | Role-relevant skill |
| Salesforce | `simple-salesforce`, added in Step 6 | Simple REST wrapper, Trailhead Dev org |
| Secrets | `.env` file, loaded with `python-dotenv`. **Never committed.** | |
| Python env | Local `.venv/` in the repo root | Homebrew Python is externally managed |

Notes for future sessions:
- Adaptive thinking is **on by default** on `claude-opus-5` — do not pass
  `budget_tokens` (it returns a 400 on this model).
- `max_tokens` is a *ceiling*, not a target. It does not increase cost by itself.
- Because thinking is on, a reply's `content` is a **list of blocks**, not a
  string — in both the raw SDK and LangChain. Use `AIMessage.text` (a property,
  not a method, in langchain-core 1.x) or a `StrOutputParser` in a chain.
- `langchain-anthropic` pins `anthropic<1.0.0`, so this project stays on the
  0.12x SDK. `requirements.txt` pins it explicitly; without the pin, installing
  LangChain silently downgrades `anthropic`.
- Git identity is set **repo-locally** (`.git/config`), not globally, and is
  deliberately kept that way.

## Structure

```
sf-case-copilot/
├── CLAUDE.md
├── requirements.txt
├── .env.example          # template; copy to .env and fill in
├── .gitignore
├── data/
│   └── sample_cases.json # mock Cases + Knowledge Articles (Step 3)
├── src/
│   ├── step1_raw_claude.py  # Step 1: raw API call, no framework
│   ├── step2_langchain.py   # Step 2: same call via LangChain + a chain
│   ├── step3_explore_data.py # Step 3: loads + validates the mock data
│   ├── step4_retrieval.py   # Step 4: scores retrieval against ground truth
│   ├── step5_agent.py       # Step 5: runs the agent, prints the loop trace
│   ├── chat.py              # interactive sandbox for the agent (multi-turn)
│   ├── step6_salesforce.py  # Step 6: org connection smoke test (no LLM calls)
│   ├── data_store.py        # reads the mock JSON — the SEAM Step 6 replaces
│   ├── retrieval.py         # keyword + IDF article search (Step 4)
│   ├── sf_client.py         # simple-salesforce wrapper (Step 6)
│   ├── tools.py             # LangChain tool definitions (Step 5)
│   ├── agent.py             # the agent loop (Step 5)
│   └── main.py              # entry point
└── tests/
```

## Build plan

Done one at a time, checking in between each.

| Step | Goal | Status |
|---|---|---|
| 1 | Raw Claude API call from a simple script — no framework | **done** |
| 2 | Wrap it in LangChain; show what the framework adds | **done** |
| 3 | Realistic mock data: ~10 Cases, ~5 Knowledge Articles as JSON | **done** |
| 4 | Simple retrieval: given a Case, find the most relevant Article(s) | **done** |
| 5 | Tools (`search_knowledge_articles`, `get_case`, `draft_resolution`) + agent loop | **done** |
| 6 | Swap mock data for a real Salesforce connection (Trailhead Dev org) | **done** |
| 7 | Tool that writes the drafted resolution back to the Case record | **done** |

## Running

```bash
source .venv/bin/activate
python src/step1_raw_claude.py    # Step 1: raw SDK
python src/step2_langchain.py     # Step 2: LangChain (makes 3 API calls)
python src/step3_explore_data.py  # Step 3: mock data (no API calls, free)
python src/step4_retrieval.py     # Step 4: retrieval + scoring (free)
python src/step5_agent.py         # Step 5: agent on case 00001042
python src/step5_agent.py 00001051  # Step 5: the no-matching-article path
python src/chat.py                # interactive: type anything, multi-turn

# Step 6 — against a real org (no LLM calls in the smoke test)
DATA_SOURCE=salesforce python src/step6_salesforce.py
DATA_SOURCE=salesforce python src/chat.py
```

## Switching data sources (Step 6)

`DATA_SOURCE=mock` (default) reads the JSON. `DATA_SOURCE=salesforce` queries the
org. `data_store.py` is the only file that knows the difference — `retrieval.py`,
`tools.py` and `agent.py` are untouched by the swap.

`sf_client.py` normalises SOQL rows into **exactly** the mock dict shape, including
mapping whatever the org calls its Knowledge body field onto the key `Answer__c`
(set `SF_KNOWLEDGE_BODY_FIELD`). Keep that normalisation intact — it is what makes
the seam work.

Two real-org gotchas already handled: article bodies are HTML and go through
`strip_html()` (otherwise the tokenizer indexes `div` and `strong` as words), and
the article query filters `PublishStatus = 'Online'` — **newly created articles are
Drafts and will not appear until published.**

### Auth (learned the hard way)

New orgs **disable SOAP `login()` by default**, and even once enabled it needs the
*Use Any API Auth* permission; Salesforce retires it entirely in Summer '27. So
`sf_client.get_connection()` prefers `SF_ACCESS_TOKEN` + `SF_INSTANCE_URL` (plain
OAuth, from `sf org display --json`) and only falls back to username/password.
Access tokens expire — `INVALID_SESSION_ID` on a previously working setup means
re-run `sf org display` and paste the new token.

### Verified against the live org

4/4 correct with `MIN_SCORE = 9.0` untouched: the login case matched its article
at 38.6, and the three unrelated Trailhead sample cases (electrical wiring,
generator, rotor) all scored ≤ 1.6 and correctly returned nothing.

## Writing back (Step 7)

`draft_resolution` writes a **CaseComment** with `IsPublished = false` — internal,
never customer-visible. That default is deliberate: everything the agent produces
awaits human review, so auto-publishing to the portal would defeat the design.
`CommentBody` caps at 4000 chars; longer drafts are cut at a word boundary and
marked, and the tool tells the model it was truncated.

Writes go through `data_store.save_draft()`, the same seam as reads — mock mode
keeps drafts in a dict, Salesforce mode creates the comment. Verified live on case
00001026 (comment `00ad200000KhAbjAAF`, `IsPublished: False`), and verified that a
case with no matching article writes **nothing**.

## The HTTP service (in-org build, phase 1)

`service/app.py` wraps the agent for Salesforce to call. `POST /draft
{case_number}` and `GET /health`. Nothing in `src/` changed to make this work.

- **`COPILOT_SHARED_SECRET` is required** — the service refuses to start without
  it rather than defaulting to unauthenticated. The Phase 3 tunnel URL is public.
- **A refusal is a 200, not an error.** `drafted: false` with the agent's reasoning
  in `summary`. The LWC must show that differently from a failure — it means the
  system worked and had nothing to say.
- **Each request calls `data_store.forget_draft()` first**, so a second button
  click leaves a new comment instead of overwriting one a colleague is reading.

### Two defects found by running it, both fixed

**Duplicate comments.** The agent re-drafts sometimes, and `draft_resolution`
always created a *new* CaseComment — one run left four drafts on one Case. Now
`save_draft` UPDATES the comment it already wrote within a run. Keep that.

**A self-critique loop I caused.** The tool used to return the draft's word count,
next to a system prompt saying "under 250 words". The model chased the target,
re-drafting four times: 51.8s instead of 22.1s for a marginally different draft.
Fixed by removing the word count from the tool response and saying "call it ONCE"
in the prompt. **Do not put metrics in a tool's success message** — the model will
optimise against them.

### Measured latency (live org, Opus 5)

~22s with an article, ~17s when refusing. The Apex callout ceiling is 120s, so
sync works — but it was 51s before the fix, which is how close this gets.

## Deployment (in-org build, phase 2)

Live at **https://sf-case-copilot.onrender.com** — Render free tier, Frankfurt,
configured by `render.yaml` (a Blueprint, so the deploy is version-controlled
rather than dashboard clicks). Free tier **sleeps after ~15 min idle**; the first
call after that takes ~40s.

Auth: this deployment uses **username + password + security token**, not an OAuth
access token. The security token does not expire on its own (only when the
password changes), which makes it the more durable choice for a long-running
service — even though it goes through the SOAP `login()` endpoint, which needed
enabling in Setup and the *Use Any API Auth* permission.

`/healthz` is liveness only and is what Render's health check points at.
`/health` also checks Salesforce — deliberately NOT the health check, because an
expired credential would make Render restart-loop an app that restarting cannot fix.

Testing: `service/try_chat.py` is a terminal client for `/chat`, and reads
`COPILOT_URL` so the same script tests local or deployed:

```bash
COPILOT_URL=https://sf-case-copilot.onrender.com python service/try_chat.py <caseId>
```

It is also the **reference implementation for the LWC** — keep a list of
`{role, content}`, send it all each turn, append the reply. That is the whole
protocol.

## The agent (Step 5)

`create_agent` (LangChain 1.x, LangGraph underneath) writes the tool loop.
`src/tools.py` holds the three tools; **their docstrings are sent to Claude
verbatim** and are the only thing it uses to pick a tool — treat them as prompt
text, not comments.

Two behaviours worth keeping working when this is refactored:
- Tools return sentences, not exceptions, for "not found". The model can recover
  from a sentence; an exception kills the loop.
- On case `00001051` the agent must refuse to draft and recommend escalation.
  `load_dotenv()` lives in `agent.py` because that is where the model is built —
  do not rely on it being imported via some other module.

## Retrieval (Step 4)

Keyword matching weighted by IDF — no embeddings, no vector DB, no extra
dependencies. Scores 10/10 on the ground truth. `MIN_SCORE = 9.0` was picked
from a threshold sweep, not guessed: the best false match scores 5.7 and the
weakest true match 11.9, so 9.0 sits between them with margin on both sides.

Caveat worth stating out loud: the corpus is 5 articles whose vocabulary was
written alongside the cases, so word overlap is unrealistically high. Expect
this to degrade on real Knowledge data where customers and article authors use
different words for the same thing — that is the point where embeddings start
to earn their complexity.

## Mock data conventions

`data/sample_cases.json` uses **real Salesforce API field names** so Step 6 is a
drop-in swap: standard `Case` fields, and `Knowledge__kav` fields where
`Answer__c` is the custom rich-text body. In a live org `Answer__c` holds HTML —
Step 6 will need to strip tags.

`_eval_ground_truth` is **not** Salesforce data. It maps each CaseNumber to the
article(s) that *should* be retrieved, so Step 4's retrieval can be measured
rather than eyeballed. Case `00001051` maps to nothing on purpose — the agent
must be able to say "no relevant article" instead of forcing a bad match.
