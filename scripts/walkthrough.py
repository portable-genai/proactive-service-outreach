"""Presenter-paced walkthrough of the live demo, with a hard assertion behind every step.

This is the script you run in front of somebody. It starts the demo server itself (and stops it
on exit), narrates each step on THIS terminal, waits for you, then performs the step and checks
that the service really reached the state the narration just claimed. The audience sees only the
clean output view; the narration never appears on the page.

It drives the server over plain HTTP with the stdlib, deliberately. A walkthrough that needed a
browser engine could not be installed offline, could not run in CI, and would rot the first time
the engine moved. Because it needs none, ``--auto`` turns the same script into the demo's
self-test (practices check F2): the demo cannot rot silently, because the same steps run
unattended on every push and fail the build when a claim stops being true.

    make demo             # presenter-paced, opens the page in a browser
    make demo-selftest    # unattended and headless, asserts every step, non-zero on failure

At a prompt: Enter runs the step, a number jumps to that step, ``r`` restarts, ``q`` quits.

Environment overrides: ``DEMO_URL`` (attach to a running server instead of spawning one),
``DEMO_PORT``, ``HEADLESS=1`` (never open a browser), ``DEMO_AUTO=1`` (do not wait for input).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

import demo

HERE = Path(__file__).resolve().parent
_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    """Colour for a real terminal, plain text when the output is captured (CI logs)."""
    return "\033[" + code + "m" + text + "\033[0m" if _TTY else text


# --------------------------------------------------------------------------------------- #
# What each step must have actually done. The demo's narration is a claim; this is the check.
# --------------------------------------------------------------------------------------- #

Check = Callable[[dict[str, Any]], list[str]]


def _facts(state: dict[str, Any]) -> dict[str, Any]:
    facts = state["steps"][-1]["facts"]
    return dict(facts) if isinstance(facts, dict) else {}


def _check_opened(state: dict[str, Any]) -> list[str]:
    facts = _facts(state)
    problems: list[str] = []
    if state["profile"] != "local":
        problems.append("expected the local profile, got " + str(state["profile"]))
    if facts.get("sdk_modules"):
        problems.append("a cloud SDK was imported: " + str(facts["sdk_modules"]))
    if len(facts.get("profiles", [])) < 3:
        problems.append("fewer than three profiles are bound for every port")
    # The policy IS the product here, so an empty policy block would make every later step
    # meaningless while still rendering a page full of green ticks.
    if len(facts.get("trigger_rules", [])) < 5:
        problems.append("fewer than five trigger rules are configured")
    if not facts.get("caps") or not facts.get("markets"):
        problems.append("the policy carries no frequency cap or no market quiet hours")
    return problems


def _check_triggers(state: dict[str, Any]) -> list[str]:
    facts = _facts(state)
    problems: list[str] = []
    fired = set(facts.get("fired", []))
    expected = {"failed_payment", "delivery_exception", "expiring_card", "fraud_hold", "outage"}
    missing = sorted(expected - fired)
    if missing:
        problems.append("these trigger types did not fire: " + str(missing))
    reasons = set(facts.get("refused_reasons", []))
    if "event_stale" not in reasons:
        problems.append("the stale event was not refused for being stale")
    if not any(r.startswith("event_attribute_missing:") for r in reasons):
        problems.append("the incomplete event was not refused for its missing attribute")
    return problems


def _check_eligibility(state: dict[str, Any]) -> list[str]:
    facts = _facts(state)
    problems: list[str] = []
    reasons = set(facts.get("refusals", []))
    # Each of these is a different way for a consent answer to be less than a clean grant, and
    # the whole claim of this step is that every one of them refuses.
    for required in (
        "consent_unknown",
        "consent_withdrawn",
        "consent_unknown_reason",
        "frequency_cap_exceeded",
        "suppressed",
        "quiet_hours",
    ):
        if required not in reasons:
            problems.append("the fail-closed case for " + required + " did not refuse")
    if int(facts.get("permitted", 0)) != 1:
        problems.append("exactly one of the seven questions should have permitted contact")
    return problems


def _check_drafting(state: dict[str, Any]) -> list[str]:
    facts = _facts(state)
    problems: list[str] = []
    if not facts.get("accepted"):
        problems.append("the grounded draft was not accepted, so the validator is over-strict")
    if not facts.get("rejected"):
        problems.append("a draft carrying an invented figure was ACCEPTED")
    invented = [
        reason
        for reason in facts.get("rejection_reasons", [])
        if str(reason).startswith("draft_ungrounded_figure")
    ]
    if not invented:
        problems.append("the rejection did not name the ungrounded figure")
    return problems


def _check_delivery(state: dict[str, Any]) -> list[str]:
    facts = _facts(state)
    problems: list[str] = []
    if int(facts.get("delivered", 0)) < 2:
        problems.append("the eligible notifications were not delivered")
    if not facts.get("consent_decision_id"):
        problems.append("the send carried no consent decision id")
    if int(facts.get("recorded_sends", 0)) < 2:
        problems.append("the sends were not recorded back, so the frequency cap counts nothing")
    if facts.get("planted_identifier_in_body"):
        problems.append("the planted identifier reached the delivered message body")
    if not facts.get("refusal_audited"):
        problems.append("a refused contact left no audit record")
    return problems


def _check_review_queue(state: dict[str, Any]) -> list[str]:
    facts = _facts(state)
    problems: list[str] = []
    if facts.get("delivered"):
        problems.append("a consequential outreach was DELIVERED rather than held")
    if not facts.get("review_ref"):
        problems.append("rule R8: the consequential result was held but never routed")
    if int(facts.get("pending", 0)) < 1:
        problems.append("the review queue holds nothing")
    if facts.get("wire_leak"):
        problems.append("personal data reached the outbound review payload")
    return problems


def _check_audit(state: dict[str, Any]) -> list[str]:
    facts = _facts(state)
    problems: list[str] = []
    if not facts.get("chain_ok"):
        problems.append("the audit chain did not verify: " + str(facts))
    if not facts.get("anchored"):
        problems.append("no external head anchor was written")
    if not facts.get("round_trip_ok"):
        problems.append("the exported trail did not reload with its chain intact")
    if int(facts.get("entries", 0)) < 3:
        problems.append("fewer audit records than decisions taken")
    if facts.get("planted_identifier_leaked"):
        problems.append("the planted identifier reached the immutable audit record")
    return problems


def _check_tamper(state: dict[str, Any]) -> list[str]:
    facts = _facts(state)
    problems: list[str] = []
    if facts.get("chain_ok"):
        problems.append("a rewritten record still verified: the chain is not tamper-evident")
    if not facts.get("detected"):
        problems.append("the report did not name the rewritten record")
    return problems


def _check_portability(state: dict[str, Any]) -> list[str]:
    facts = _facts(state)
    expected = sorted(demo.EXIT_CALLS)
    completed = sorted([*facts.get("refused", []), *facts.get("absent", [])])
    if completed != expected:
        return ["the exit profile did not account for every seam: " + str(completed)]
    return []


#: One entry per step key, in the demo's order. A step added to ``demo.STEPS`` without a check
#: here fails the walkthrough immediately, so the arc and its assertions cannot drift.
CHECKS: dict[str, Check] = {
    "opened": _check_opened,
    "triggers": _check_triggers,
    "eligibility": _check_eligibility,
    "drafting": _check_drafting,
    "delivery": _check_delivery,
    "review_queue": _check_review_queue,
    "audit": _check_audit,
    "tamper": _check_tamper,
    "portability": _check_portability,
}


# --------------------------------------------------------------------------------------- #
# Driving the server
# --------------------------------------------------------------------------------------- #


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _get(url: str, path: str) -> dict[str, Any]:
    with urllib.request.urlopen(url + path, timeout=10) as response:  # noqa: S310 - loopback
        payload = json.loads(response.read().decode("utf-8"))
    return dict(payload)


def _post(url: str, path: str) -> None:
    request = urllib.request.Request(url + path, data=b"", method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - loopback
        response.read()


def _wait_for(url: str, process: subprocess.Popen[bytes] | None, seconds: float = 30.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise SystemExit("the demo server exited before it was ready")
        try:
            _get(url, "/healthz")
            return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.1)
    raise SystemExit("the demo server never became ready at " + url)


def _print_step(state: dict[str, Any]) -> None:
    step = state["steps"][-1]
    number = str(int(state["step_index"]) + 1) + "/" + str(state["step_count"])
    print("")
    print(_c("1;36", "  step " + number + ": " + str(step["label"])))
    for panel in step["panels"]:
        print(_c("1", "    " + panel["title"]))
        for row in panel["rows"]:
            print("      " + str(row["label"]) + ": " + str(row["value"]))


def _prompt(state: dict[str, Any], auto: bool) -> str:
    """Return the presenter's instruction: ``next``, ``restart``, ``quit`` or a step number."""
    upcoming = state["next"] or "finish"
    print("")
    print(_c("0;33", "  next: " + str(upcoming)))
    if auto:
        return "next"
    try:
        answer = input("  [Enter] run  [number] jump  [r] restart  [q] quit > ").strip().lower()
    except EOFError:
        return "quit"
    if answer in ("q", "quit"):
        return "quit"
    if answer in ("r", "restart"):
        return "restart"
    if answer.isdigit():
        return answer
    return "next"


def run(url: str, *, auto: bool, headless: bool, process: subprocess.Popen[bytes] | None) -> int:
    _wait_for(url, process)
    state = _get(url, "/state")
    if not headless:
        webbrowser.open(url)

    print(_c("1", state["repository"] + " ( walkthrough"))
    print("  " + url + "  profile=" + str(state["profile"]) + " region=" + str(state["region"]))

    failures: list[str] = []
    seen: list[str] = []
    while True:
        key = str(state["step"])
        if key not in CHECKS:
            failures.append("step '" + key + "' has no expectation in walkthrough.CHECKS")
            break
        problems = CHECKS[key](state)
        _print_step(state)
        print("")
        print("  " + _c("0;37", demo.STEPS[int(state["step_index"])].narration))
        if problems:
            for problem in problems:
                print("  " + _c("1;31", "FAIL: " + problem))
            failures.extend(key + ": " + problem for problem in problems)
        else:
            print("  " + _c("1;32", "checks passed"))
        seen.append(key)

        if state["done"]:
            break
        instruction = _prompt(state, auto)
        if instruction == "quit":
            print("  quit before the end; nothing was asserted about the remaining steps")
            return 1 if failures else 0
        if instruction == "restart":
            _post(url, "/restart")
            state = _get(url, "/state")
            seen = []
            continue
        if instruction.isdigit():
            target = max(1, min(int(instruction), int(state["step_count"])))
            while int(state["step_index"]) + 1 < target and not state["done"]:
                _post(url, "/next")
                state = _get(url, "/state")
            continue
        _post(url, "/next")
        state = _get(url, "/state")

    missing = [key for key in demo.STEP_KEYS if key not in seen]
    if missing:
        failures.append("steps never reached: " + ", ".join(missing))

    print("")
    if failures:
        print(_c("1;31", "DEMO WALKTHROUGH: FAILED"))
        for failure in failures:
            print("  - " + failure)
        return 1
    print(_c("1;32", "DEMO WALKTHROUGH: PASS (" + str(len(seen)) + " steps asserted)"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Presenter-paced walkthrough of the live demo.")
    parser.add_argument("--url", default=os.environ.get("DEMO_URL", ""))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DEMO_PORT", "0")))
    parser.add_argument(
        "--auto",
        action="store_true",
        default=os.environ.get("DEMO_AUTO") == "1",
        help="advance without waiting for the presenter (the self-test)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=os.environ.get("HEADLESS") == "1",
        help="never open a browser window",
    )
    args = parser.parse_args(argv)

    if args.url:
        return run(args.url.rstrip("/"), auto=args.auto, headless=args.headless, process=None)

    port = args.port or _free_port()
    command = [sys.executable, str(HERE / "demo_server.py"), "--port", str(port)]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        return run(
            "http://127.0.0.1:" + str(port),
            auto=args.auto,
            headless=args.headless,
            process=process,
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - a wedged child
            process.kill()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
