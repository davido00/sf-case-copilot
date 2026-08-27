"""
A terminal client for POST /chat, so you can hold a conversation without
hand-editing JSON.

This is also the reference for what the LWC has to do in Step 5: keep a list of
{role, content} messages, send the whole list plus the new message every turn,
and append the reply. That is the entire protocol.

Run the service in one terminal:
    DATA_SOURCE=salesforce .venv/bin/uvicorn service.app:app --port 8000

And this in another:
    .venv/bin/python service/try_chat.py                    # picks a case for you
    .venv/bin/python service/try_chat.py 500d200003LxNKlAAN # a specific Case Id

Commands: history | reset | quit
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ.get("COPILOT_URL", "http://127.0.0.1:8000")
SECRET = os.environ.get("COPILOT_SHARED_SECRET", "")


def post(path: str, payload: dict, timeout: int = 240) -> dict:
    """POST JSON and return the parsed reply, or raise with the server's message."""
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Copilot-Secret": SECRET},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"\nHTTP {exc.code} from {path}:\n{detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"\nCould not reach {BASE_URL}: {exc.reason}\n"
            "Is the service running?\n"
            "    DATA_SOURCE=salesforce .venv/bin/uvicorn service.app:app --port 8000"
        )


def pick_case() -> tuple[str, str]:
    """Find a Case to talk about, so you do not have to look one up first."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    import data_store

    cases = data_store.list_cases()
    if not cases:
        raise SystemExit("No cases available from the current DATA_SOURCE.")

    print("Cases available:\n")
    for index, case in enumerate(cases, 1):
        print(f"  {index}. {case['CaseNumber']}  {case['Subject'][:58]}")

    choice = input("\nPick a number (Enter for 1): ").strip() or "1"
    try:
        case = cases[int(choice) - 1]
    except (ValueError, IndexError):
        raise SystemExit("Not a valid choice.")
    return case["Id"], f"{case['CaseNumber']} — {case['Subject']}"


def main() -> None:
    if not SECRET:
        raise SystemExit("COPILOT_SHARED_SECRET is not set. It should be in your .env.")

    health = json.loads(urllib.request.urlopen(f"{BASE_URL}/health", timeout=10).read())
    print(f"service: {BASE_URL}  |  data source: {health['data_source']}  |  salesforce: {health['salesforce']}")
    print()

    if len(sys.argv) > 1:
        case_id, label = sys.argv[1], sys.argv[1]
    else:
        case_id, label = pick_case()

    print(f"\n{'=' * 70}\nChatting about: {label}\nCommands: history | reset | quit\n{'=' * 70}")

    # THE ENTIRE PROTOCOL: this list, sent in full every turn. The service keeps
    # nothing between requests -- which is why it can restart or sleep without
    # losing your conversation.
    history: list[dict] = []

    while True:
        try:
            message = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return

        if not message:
            continue
        if message.lower() in {"quit", "exit", "q"}:
            print("bye")
            return
        if message.lower() == "reset":
            history = []
            print("  (history cleared)")
            continue
        if message.lower() == "history":
            print(f"  {len(history)} messages, {sum(len(m['content']) for m in history)} chars")
            for m in history:
                print(f"    {m['role']:<9} {m['content'][:70]!r}")
            continue

        started = time.perf_counter()
        result = post("/chat", {"case_id": case_id, "history": history, "message": message})
        elapsed = time.perf_counter() - started

        tools = ", ".join(result["tools_called"]) or "no tools"
        print(f"\n[{elapsed:.1f}s · {tools} · {len(history)} msgs of history sent]\n")
        print(result["reply"])

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": result["reply"]})


if __name__ == "__main__":
    main()
