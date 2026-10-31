import argparse

from whoneedsacoach.agent.executor import run_chat, run_checkin


def main() -> None:
    parser = argparse.ArgumentParser(prog="coach")
    sub = parser.add_subparsers(dest="cmd", required=True)
    chat = sub.add_parser("chat")
    chat.add_argument("--user", required=True)
    sub.add_parser("checkin")
    args = parser.parse_args()
    if args.cmd == "chat":
        run_chat(args.user)
    else:
        run_checkin()
