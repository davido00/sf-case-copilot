# sf-case-copilot

A tool-calling LLM agent that reads a Salesforce Support Case, retrieves the
relevant Knowledge Article, drafts a resolution grounded in that article, and
writes the draft back to the Case as an internal comment for human review.

Built against a real Salesforce org — not a mock.

**This is deliberately the raw, hand-built version.** It is not how I would
recommend shipping this to a customer. [See below](#why-i-built-this-the-hard-way).

```
[step 1] get_case(case_number='00001026')
      -> Case 00001026: Cannot log in to Community portal after password reset
[step 2] search_knowledge_articles(query='Experience Cloud login failure after reset')
      -> Article 000001003 (relevance 38.6): Troubleshooting Experience Cloud Login Failures
[step 3] draft_resolution(case_number='00001026', draft_text='Hi, Thanks for the details...')
      -> Saved as internal Case Comment 00ad200000KhAbjAAF (not visible to the customer)
```

The agent chose that sequence itself. Nothing in the code hard-codes it.

## The behaviour I care most about

Given a case the Knowledge Base does not cover, it refuses to answer:

```
[step 2] search_knowledge_articles(query='electrical wiring installation GC5060 generator')
      -> No relevant knowledge articles found.
[step 3] search_knowledge_articles(query='wiring requirements voltage connection setup')
      -> No relevant knowledge articles found.

SAVED DRAFTS: (none)
comments on record: 0
```

It searched twice — narrowing, then broadening — then declined to draft and
recommended escalation. **Nothing was written to Salesforce.** A support tool
that invents plausible troubleshooting steps from an irrelevant article is worse
than no tool at all, so this is the case I test first.

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
| `tools.py` — three tool definitions | Agentforce Topics and Actions |
| The system prompt in `agent.py` | Prompt Builder templates |
| `retrieval.py` — IDF keyword scoring | Data Cloud retrievers / vector search |
| `data_store.py` — the mock/live seam | Data Cloud's unified data model |
| `sf_client.py` — SOQL and auth plumbing | Zero-copy ingestion, Named Credentials |
| `draft_resolution` writing a CaseComment | An Agentforce Action |
| *nothing* | Einstein Trust Layer — masking, audit, toxicity gating |

That last row is the honest one. My version has no PII masking, no audit trail,
and no guardrails beyond a system prompt — which is precisely the kind of thing
you stop taking for granted once you have tried to build it yourself.

Writing the retrieval scoring by hand is what made "grounding" concrete rather
than a slide. Writing the tool loop is what made it obvious that tool
descriptions are prompt engineering. I would rather configure Agentforce knowing
that than knowing only which buttons to click.

## Architecture

```
     agent.py            create_agent() runs the tool loop
        |
     tools.py            3 tools; their docstrings ARE the prompt
        |
   +----+--------------------+
   |                         |
retrieval.py            data_store.py     <-- the seam
keyword + IDF                 |
                     +--------+--------+
                     |                 |
              sample_cases.json    sf_client.py
              (DATA_SOURCE=mock)   (DATA_SOURCE=salesforce)
```

`data_store.py` is the only module that knows where data comes from.
`sf_client.py` normalises SOQL rows into exactly the shape the JSON uses, so
switching between mock data and a live org is one environment variable and
touches nothing else — including the write path.

That mattered in practice: the entire agent was built and debugged offline for
free, then pointed at a real org without changing a line of `retrieval.py`,
`tools.py` or `agent.py`.

## Decisions worth defending

**Keyword retrieval with IDF weighting, not embeddings.** Words appearing in
every article score zero; rare words score high. It gets 10/10 on the mock
ground truth and 4/4 against the live org. Adding a vector database would be
complexity I could not yet justify from evidence — and I can now describe
exactly which failure would justify it.

**The relevance threshold was measured, not guessed.** `MIN_SCORE = 9.0` comes
from a sweep: the best false match scores 5.7, the weakest true match 11.9.
Several values score perfectly; 9.0 sits between them with margin on both sides
rather than 0.3 above a known false positive. It held on live data without
retuning.

**Tools return sentences, not exceptions.** `get_case("99999999")` returns
`"No case found with number 99999999."` The model reads that and recovers. A
raised exception kills the agent loop.

**Drafts write as `IsPublished = false`.** A published CaseComment is visible to
the customer. Everything here awaits human review, so auto-publishing would
defeat the design. Making it customer-visible is a deliberate flag change.

**OAuth, not SOAP `login()`.** New orgs disable the SOAP login endpoint by
default and Salesforce retires it in Summer '27, so the client prefers an OAuth
access token and only falls back to username/password.

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add your Anthropic key
```

Offline, free, no Salesforce needed:

```bash
python src/step4_retrieval.py     # retrieval scored against ground truth
python src/step5_agent.py         # full agent run with the tool trace printed
python src/chat.py                # interactive, multi-turn
```

Against a real org — see `.env.example` for credentials:

```bash
DATA_SOURCE=salesforce python src/step6_salesforce.py   # connection check, no LLM calls
DATA_SOURCE=salesforce python src/chat.py
```

The `stepN_*.py` files are deliberate teaching artifacts — each step is
independently runnable, starting from a raw API call with no framework and
ending at the full agent. `CLAUDE.md` is the build log.

## Honest limitations

- **The retrieval score is flattering.** I wrote the mock cases and articles, so
  their vocabulary overlaps more than real data would. The live test used three
  Trailhead sample cases I did not write — they correctly returned nothing — but
  that tests rejection, not matching. Real Knowledge bases, where customers
  describe symptoms and authors describe causes, will score worse.
- **Word limits are suggestions.** The prompt says "under 250 words"; a draft
  came out at 293. Prompt rules are not constraints. A hard limit needs code.
- **Access tokens expire.** `INVALID_SESSION_ID` on a working setup means
  re-running `sf org display --json`.
- **No tests.** Verification here is the runnable step scripts and the live
  smoke test, not a suite.

## Stack

Python 3.11 · `anthropic` · LangChain 1.x (`create_agent`, LangGraph) ·
`simple-salesforce` · Claude Opus 5
