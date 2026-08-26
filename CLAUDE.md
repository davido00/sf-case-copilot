# sf-case-copilot

## What this is

A learning/portfolio project: a **LangChain agent that reads Salesforce Support Cases,
retrieves relevant Knowledge Articles, drafts a resolution with an LLM, and writes the
draft back to the Case record.**

Built as interview prep for a **Forward Deployed Engineer (FDE)** role at Salesforce
(Polish-speaking). The point is to demonstrate: LLM agent development, LangChain,
tool-calling, RAG, and Salesforce integration — from the perspective of an experienced
Salesforce developer who is new to Python and LLMs.

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
