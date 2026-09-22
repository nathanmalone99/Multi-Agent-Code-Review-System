#!/usr/bin/env python3
"""
Multi-agent code review system powered by a local Ollama instance.

Runs four specialist review agents (security, performance, testing,
documentation) in parallel against a code diff/file, then feeds their
findings to a lead reviewer agent that synthesizes one final report.

Usage:
    python review.py path/to/diff_or_file.txt
    python review.py path/to/diff_or_file.txt --model qwen2.5-coder:7b
    git diff main | python review.py -            # read from stdin
    python review.py file.py --out reports/out.md

Requirements:
    pip install requests --break-system-packages
    Ollama running locally (default http://localhost:11434) with a model
    pulled, e.g.:
        ollama pull qwen2.5-coder:7b
"""

import argparse
import concurrent.futures
import datetime
import json
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
AGENTS_DIR = SCRIPT_DIR / "agents"
REPORTS_DIR = SCRIPT_DIR / "reports"

SPECIALIST_AGENTS = {
    "security": "security.md",
    "performance": "performance.md",
    "testing": "testing.md",
    "documentation": "documentation.md",
}
LEAD_AGENT_FILE = "lead_reviewer.md"

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_TIMEOUT = 300  # seconds, local models on CPU can be slow


def load_system_prompt(filename: str) -> str:
    path = AGENTS_DIR / filename
    if not path.exists():
        sys.exit(f"Missing agent prompt file: {path}")
    return path.read_text(encoding="utf-8")


def call_ollama(system_prompt: str, user_content: str, model: str,
                 url: str, timeout: int) -> str:
    """Send a single chat request to Ollama and return the assistant text."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "options": {
            "temperature": 0.2,  # reviews should be consistent, not creative
        },
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Could not connect to Ollama at {url}. "
            f"Is `ollama serve` running?"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(f"Ollama request timed out after {timeout}s.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Ollama returned an error: {e}. "
                            f"Check the model name is pulled (`ollama list`).")

    data = resp.json()
    try:
        return data["message"]["content"]
    except (KeyError, TypeError):
        raise RuntimeError(f"Unexpected Ollama response shape: {json.dumps(data)[:500]}")


def run_specialist(name: str, filename: str, code_content: str, model: str,
                    url: str, timeout: int) -> tuple[str, str]:
    system_prompt = load_system_prompt(filename)
    user_content = (
        f"Review the following code/diff.\n\n"
        f"```\n{code_content}\n```"
    )
    print(f"  -> [{name}] sending to {model} ...", file=sys.stderr)
    result = call_ollama(system_prompt, user_content, model, url, timeout)
    print(f"  <- [{name}] done ({len(result)} chars)", file=sys.stderr)
    return name, result


def run_lead_reviewer(specialist_reports: dict, model: str, url: str,
                       timeout: int) -> str:
    system_prompt = load_system_prompt(LEAD_AGENT_FILE)
    parts = []
    for name, report in specialist_reports.items():
        parts.append(f"## {name.capitalize()} Agent Report\n\n{report}")
    user_content = "\n\n---\n\n".join(parts)
    print("  -> [lead_reviewer] synthesizing ...", file=sys.stderr)
    result = call_ollama(system_prompt, user_content, model, url, timeout)
    print("  <- [lead_reviewer] done", file=sys.stderr)
    return result


def main():
    parser = argparse.ArgumentParser(description="Multi-agent code review via local Ollama")
    parser.add_argument("input", help="Path to a file/diff to review, or '-' for stdin")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                         help=f"Ollama model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--url", default=DEFAULT_OLLAMA_URL,
                         help=f"Ollama chat endpoint (default: {DEFAULT_OLLAMA_URL})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                         help=f"Per-request timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--out", default=None,
                         help="Output path for the final markdown report "
                              "(default: reports/review_<timestamp>.md)")
    parser.add_argument("--sequential", action="store_true",
                         help="Run specialist agents one at a time instead of in parallel "
                              "(use this if your machine/model can't handle concurrent requests)")
    args = parser.parse_args()

    if args.input == "-":
        code_content = sys.stdin.read()
    else:
        in_path = Path(args.input)
        if not in_path.exists():
            sys.exit(f"Input file not found: {in_path}")
        code_content = in_path.read_text(encoding="utf-8")

    if not code_content.strip():
        sys.exit("Input is empty, nothing to review.")

    REPORTS_DIR.mkdir(exist_ok=True)

    print(f"Running specialist agents against model '{args.model}' at {args.url}", file=sys.stderr)

    specialist_reports: dict[str, str] = {}
    errors: dict[str, str] = {}

    if args.sequential:
        for name, filename in SPECIALIST_AGENTS.items():
            try:
                _, report = run_specialist(name, filename, code_content, args.model, args.url, args.timeout)
                specialist_reports[name] = report
            except RuntimeError as e:
                errors[name] = str(e)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(SPECIALIST_AGENTS)) as executor:
            futures = {
                executor.submit(run_specialist, name, filename, code_content, args.model, args.url, args.timeout): name
                for name, filename in SPECIALIST_AGENTS.items()
            }
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    _, report = future.result()
                    specialist_reports[name] = report
                except RuntimeError as e:
                    errors[name] = str(e)

    if errors:
        print("\nErrors from specialist agents:", file=sys.stderr)
        for name, err in errors.items():
            print(f"  [{name}] {err}", file=sys.stderr)
        if not specialist_reports:
            sys.exit("All specialist agents failed. Aborting — check Ollama is running "
                      "and the model is pulled.")
        print("Continuing with partial results...\n", file=sys.stderr)

    lead_report = run_lead_reviewer(specialist_reports, args.model, args.url, args.timeout)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else REPORTS_DIR / f"review_{timestamp}.md"

    full_report = [f"# Multi-Agent Code Review\n"]
    full_report.append(f"*Generated {datetime.datetime.now().isoformat(timespec='seconds')} "
                        f"using model `{args.model}`*\n")
    full_report.append("---\n")
    full_report.append(lead_report)
    full_report.append("\n---\n")
    full_report.append("## Appendix: Full Specialist Reports\n")
    for name in SPECIALIST_AGENTS:
        full_report.append(f"\n<details>\n<summary>{name.capitalize()} Agent — full report</summary>\n")
        if name in specialist_reports:
            full_report.append(f"\n{specialist_reports[name]}\n")
        else:
            full_report.append(f"\n_Agent failed: {errors.get(name, 'unknown error')}_\n")
        full_report.append("\n</details>\n")

    out_path.write_text("\n".join(full_report), encoding="utf-8")
    print(f"\nFinal report written to: {out_path}", file=sys.stderr)
    print(out_path)


if __name__ == "__main__":
    main()
