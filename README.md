# Multi-Agent Code Review System

Five agents, defined as plain markdown prompts, orchestrated by a small
Python script that talks to a **local Ollama** instance. No cloud calls,
no framework — just prompts + `requests`.

```
code-review-system/
├── agents/
│   ├── security.md        # vulnerabilities
│   ├── performance.md     # inefficiencies
│   ├── testing.md         # missing test coverage
│   ├── documentation.md   # comment/docs quality
│   └── lead_reviewer.md   # aggregates the four reports above
├── reports/                # generated review output lands here
├── review.py               # orchestrator
└── README.md
```

## How it works

1. You give `review.py` a diff or file.
2. The four specialist agents run **in parallel**, each with its own
   markdown system prompt, each blind to the others' findings.
3. Their four reports are handed to the **lead reviewer** agent, which
   dedupes, prioritizes by real risk, and produces one final verdict.
4. Everything is written to `reports/review_<timestamp>.md`, including
   the full specialist reports in collapsible sections.

## Setup

1. Install and start Ollama: https://ollama.com
   ```bash
   ollama serve
   ```
2. Pull a model good at code (pick one based on your hardware):
   ```bash
   ollama pull qwen2.5-coder:14b   # good balance, needs ~16GB RAM
   ollama pull qwen2.5-coder:7b    # lighter
   ollama pull deepseek-coder-v2   # alternative
   ```
3. Install the one Python dependency:
   ```bash
   pip install requests
   ```

## Usage

```bash
# Review a file
python review.py path/to/file.py

# Review a git diff
git diff main > /tmp/changes.diff
python review.py /tmp/changes.diff

# Pipe a diff straight in
git diff main | python review.py -

# Use a different model
python review.py file.py --model deepseek-coder-v2

# If your machine can't handle 4 concurrent model calls, run one at a time
python review.py file.py --sequential

# Custom output path
python review.py file.py --out my_review.md
```

## Tuning the agents

Each agent is just a markdown file in `agents/`. Edit the "What to look
for" and "Output format" sections directly — no code changes needed. Keep
the output format tables intact if you want the lead reviewer's synthesis
to parse cleanly; it reads the specialist reports as plain text, so it's
tolerant of format drift, but consistent tables produce better summaries.

## Notes / gotchas

- **Concurrency vs. VRAM**: running 4 parallel requests against one Ollama
  instance means 4 concurrent model loads/inferences. If you only have one
  GPU and a large model, Ollama will queue them anyway, or you may want
  `--sequential` to avoid timeouts.
- **Context length**: very large diffs may exceed the model's context
  window. Consider reviewing per-file or per-module for big changes rather
  than a full repo diff.
- **Determinism**: temperature is set to 0.2 in `review.py` for more
  consistent review output. Adjust in `call_ollama()` if you want more
  variety.
- **Timeouts**: local CPU inference can be slow. Default timeout is 300s
  per agent call; raise with `--timeout` if you're seeing failures on a
  slower machine.
