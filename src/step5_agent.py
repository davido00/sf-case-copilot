"""
Step 5: run the agent and watch the loop.

This prints every step the agent took -- each tool it chose, the arguments it
chose, and what came back -- so the loop is something you can see rather than
something you take on faith.

Run it:
    source .venv/bin/activate
    python src/step5_agent.py            # defaults to case 00001042
    python src/step5_agent.py 00001051   # the case with no matching article
"""

import sys

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import agent as agent_module
import data_store


def shorten(text: str, limit: int = 240) -> str:
    """Trim long tool output so the trace stays readable."""
    text = text.replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit] + " ..."


def print_trace(messages: list) -> None:
    """Walk the conversation and show what happened at each step."""
    step = 0
    for message in messages:
        if isinstance(message, HumanMessage):
            print(f"\n[user] {message.content}")

        elif isinstance(message, AIMessage):
            # An AIMessage either asks for tools or gives the final answer.
            # `.tool_calls` is LangChain's normalised view of the `tool_use`
            # blocks you saw raw in Step 1.
            if message.tool_calls:
                for call in message.tool_calls:
                    step += 1
                    args = ", ".join(
                        f"{k}={shorten(str(v), 60)!r}" for k, v in call["args"].items()
                    )
                    print(f"\n[step {step}] Claude wants: {call['name']}({args})")
            elif message.text.strip():
                print(f"\n[final answer]\n{message.text}")

        elif isinstance(message, ToolMessage):
            # The result our code produced and handed back to Claude.
            print(f"          -> {shorten(message.content)}")


def main() -> None:
    case_number = sys.argv[1] if len(sys.argv) > 1 else "00001042"

    print("=" * 78)
    print(f"AGENT RUN -- case {case_number}")
    print("=" * 78)

    the_agent = agent_module.build_agent()
    result = agent_module.run(the_agent, f"Draft a resolution for case {case_number}.")

    print_trace(result["messages"])

    # Did the agent actually save anything? For a case with no matching
    # article it should NOT have -- that is the behaviour we care about.
    print()
    print("=" * 78)
    print("SAVED DRAFTS")
    print("=" * 78)
    if data_store.saved_drafts():
        for number, entry in data_store.saved_drafts().items():
            where = f" (Case Comment {entry['comment_id']})" if entry["comment_id"] else ""
            print(f"\n--- case {number}{where} ---\n{entry['text']}")
    else:
        print("(none -- the agent chose not to save a draft)")


if __name__ == "__main__":
    main()
