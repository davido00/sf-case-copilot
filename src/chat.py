"""
An interactive sandbox for the Step 5 agent. Type whatever you like.

Unlike step5_agent.py, which runs one fixed request and exits, this keeps the
conversation going -- the agent remembers what was said earlier in the session,
so you can follow up ("make that shorter", "why did you pick that article?").

Run it:
    source .venv/bin/activate
    python src/chat.py

Commands: cases | drafts | reset | quit
"""

import agent as agent_module
import data_store
import tools
from step5_agent import print_trace

BANNER = """
==============================================================================
 sf-case-copilot -- interactive agent
==============================================================================
 Try:
   Draft a resolution for case 00001045.
   What is case 00001050 about?
   Search the knowledge base for problems with duplicate records.
   Draft a resolution for case 00001051.        <- no article exists
   Which of our cases are about integrations?

 Follow-ups work too -- it remembers the conversation:
   Make that draft shorter.
   Why did you choose that article?

 Commands: cases | drafts | reset | quit
=============================================================================="""


def show_cases() -> None:
    """Print the case list so you know what there is to ask about."""
    for case in data_store.list_cases():
        print(f"  {case['CaseNumber']}  {case['Priority']:<9} {case['Subject']}")


def show_drafts() -> None:
    """Print whatever the agent has saved so far this session."""
    if not tools.DRAFTS:
        print("  (no drafts saved yet)")
        return
    for number, draft in tools.DRAFTS.items():
        print(f"\n  --- case {number} ---")
        for line in draft.splitlines():
            print(f"  {line}")


def main() -> None:
    print(BANNER)
    the_agent = agent_module.build_agent()

    # The running conversation. We pass the WHOLE list to the agent every turn
    # and keep what comes back -- that is how the agent has any memory at all.
    # Remember from Step 1: the API itself is stateless. Nothing is remembered
    # on Anthropic's side; this list IS the memory.
    history = []

    while True:
        try:
            user_input = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if not user_input:
            continue

        lowered = user_input.lower()
        if lowered in {"quit", "exit", "q"}:
            print("bye")
            break
        if lowered == "cases":
            show_cases()
            continue
        if lowered == "drafts":
            show_drafts()
            continue
        if lowered == "reset":
            history = []
            print("  (conversation cleared -- saved drafts kept)")
            continue

        history.append({"role": "user", "content": user_input})

        try:
            result = the_agent.invoke({"messages": history})
        except Exception as exc:
            # Don't let one bad turn kill the session -- you are experimenting.
            print(f"\n  error: {type(exc).__name__}: {exc}")
            history.pop()
            continue

        # Only show what is NEW this turn, not the whole conversation again.
        print_trace(result["messages"][len(history):])

        # Keep the agent's own version of the history, which now includes the
        # tool calls and their results.
        history = result["messages"]


if __name__ == "__main__":
    main()
