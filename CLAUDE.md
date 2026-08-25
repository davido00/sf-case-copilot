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
| 3 | Realistic mock data: ~10 Cases, ~5 Knowledge Articles as JSON | **next** |
| 4 | Simple retrieval: given a Case, find the most relevant Article(s) | todo |
| 5 | Tools (`search_knowledge_articles`, `get_case`, `draft_resolution`) + agent loop | todo |
| 6 | Swap mock data for a real Salesforce connection (Trailhead Dev org) | todo |
| 7 | Tool that writes the drafted resolution back to the Case record | todo |

## Running

```bash
source .venv/bin/activate
python src/step1_raw_claude.py   # Step 1: raw SDK
python src/step2_langchain.py    # Step 2: LangChain (makes 3 API calls)
```
