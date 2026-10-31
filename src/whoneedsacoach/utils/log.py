import json

from whoneedsacoach.utils.config import LOG_PATH


def write_log(title: str, payload) -> None:
    body = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"\n=== {title} ===\n{body}\n")


def show(title: str, payload) -> None:
    body = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    print(f"\n=== {title} ===\n{body}", flush=True)
    write_log(title, payload)


def note(message: str) -> None:
    """One progress line on the terminal and in the log, flushed before the next wait."""
    print(message, flush=True)
    write_log("progress", message)
