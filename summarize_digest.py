"""
Summarize digest tweets via codex exec gpt-5.4-mini.
Reads JSON array of tweet objects from stdin (output of filter_digest.py --output json).
Outputs ready-to-post markdown, one tweet per line:
  **@handle** — ❤️N 🔁N
  One-line summary.
  https://x.com/...

Usage:
    cat tweets.json | python summarize_digest.py
"""
import json
import subprocess
import sys
import re


def summarize_batch(tweets: list) -> list[str]:
    """
    Send tweets to codex exec gpt-5.4-mini for one-line summarization.
    Returns list of one-line summaries in order.
    """
    prompt_lines = ["Summarize each tweet below into ONE concise English sentence. Keep key facts and numbers. Output ONLY the summaries, one per line, in the same order. No numbering, no extra text.\n"]
    for i, t in enumerate(tweets, 1):
        text = t.get('text', '').replace('\n', ' ').strip()
        prompt_lines.append(f"{i}. {text}")

    prompt = "\n".join(prompt_lines)

    result = subprocess.run(
        ["codex", "exec", "--model", "gpt-5.4-mini", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=120,
    )

    # codex exec outputs the model response to stdout or stderr
    output = result.stdout.strip() or result.stderr.strip()

    # Extract lines that look like summaries (non-empty, not codex noise)
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    # Filter out codex meta lines (e.g. "Model: ...", "Task: ...")
    summaries = [l for l in lines if not re.match(r'^(Model|Task|Working|Done|Error|>|#|\[)[\s:]', l)]

    return summaries


def format_tweet(t: dict, summary: str) -> str:
    handle = t.get('handle', '?')
    likes = t.get('likes', '0')
    retweets = t.get('retweets', '0')
    link = t.get('link', '')
    lines = [f"**@{handle}** — ❤️{likes} 🔁{retweets}", summary]
    if link:
        lines.append(link)
    return "\n".join(lines)


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(1)

    tweets = json.loads(raw)
    if not tweets:
        sys.exit(1)

    # Process in batches of 15 to stay within codex context
    batch_size = 15
    all_summaries = []
    for i in range(0, len(tweets), batch_size):
        batch = tweets[i:i + batch_size]
        summaries = summarize_batch(batch)
        # Pad if codex returned fewer lines than expected
        while len(summaries) < len(batch):
            idx = len(summaries)
            summaries.append(batch[idx].get('text', '')[:120].replace('\n', ' '))
        all_summaries.extend(summaries[:len(batch)])

    # Format and output
    parts = []
    for t, summary in zip(tweets, all_summaries):
        parts.append(format_tweet(t, summary))

    print("\n\n".join(parts))


if __name__ == '__main__':
    main()
