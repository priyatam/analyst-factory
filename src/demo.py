"""Run both paths against the deployed AgentCore Runtime.

    export NOVAMARK_RUNTIME_ARN=<runtime ARN>
    uv run python src/demo.py            # ask at each review
    uv run python src/demo.py --auto     # approve each review, no one at the keyboard

The display is `cli.py`. A tidy filing (AAPL) and a garbled one (NVDA) each pause for a
senior analyst and a compliance officer. Every new run makes real model calls, billed
to the account that owns the runtime.
"""
import sys

from rich.console import Console
from rich.prompt import Prompt

from cli import require_arn, run

RUNS = (("tidy filing", "AAPL"), ("garbled filing", "NVDA"))
ACTIONS = ("approve", "reject")


def decision(action: str, reviewer: str, comment: str) -> dict:
    """One reviewer's answer. The role comes from the gate, not from this dict."""
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    if not reviewer.strip():
        raise ValueError("a reviewer name is required")
    return {"action": action, "reviewer": reviewer.strip(), "comment": comment}


def again(gate: str) -> str:
    """What a rejection just did, said once before the same person is asked again."""
    if gate == "senior_review":
        return ("The model extracted the figures again, so the scores can differ from the review you just rejected.")
    return ("The memo was rewritten from the same figures, using your comment. The scores are unchanged.")


def reviewer():
    """Ask at each gate, and say what a rejection changed before asking the next time."""
    last: dict[str, tuple[str, str]] = {}

    def ask(packet: dict, console: Console) -> dict:
        prior = last.get(packet["run_id"])
        if prior and prior[0] == "reject":
            console.print(f"\n[bold yellow]{again(prior[1])}[/]")
        console.print(f"\n[bold]{packet['gate']}[/] is waiting for a [bold]{packet['role']}[/].")
        action = Prompt.ask("action", choices=list(ACTIONS), console=console)
        name = Prompt.ask("your name", console=console)
        while not name.strip():
            name = Prompt.ask("your name", console=console)
        comment = Prompt.ask("comment", default="", console=console)
        last[packet["run_id"]] = (action, packet["gate"])
        return decision(action, name, comment)

    return ask


def auto(packet: dict, console: Console) -> dict:
    """Approve without asking. The reviewer name is the demo, not a person."""
    return decision("approve", "demo", f"approved {packet['gate']} with --auto")


def main(argv: list[str] | None = None) -> int:
    """Both runs. `--auto` approves every review. Otherwise the demo asks."""
    import argparse

    parser = argparse.ArgumentParser(description="Run both memos on the deployed runtime")
    parser.add_argument("--auto", action="store_true",
                        help="approve each review without asking")
    args = parser.parse_args(argv)
    try:
        arn = require_arn()
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1
    decide = auto if args.auto else reviewer()
    for label, ticker in RUNS:
        code = run(arn, ticker, label, decide=decide)
        if code:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
