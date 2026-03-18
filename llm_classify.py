"""
LLM-based tweet classifier using Codex CLI (gpt-5.4-mini).
Reads JSON array of tweets from stdin.
Outputs same JSON array with an added `verdict` field per tweet:
  - "quality" : substantive, insightful content worth reading
  - "spam"    : promotional, low-effort, emotional rant — mark Not Interested
  - "skip"    : neutral, not spam but not worth including

All tweets batched into a single codex --print call to minimize overhead.
"""
import json
import subprocess
import sys

MODEL = "gpt-5.4-mini"

PROMPT_TEMPLATE = """You are a strict curator for a high-signal Twitter digest.
Classify each tweet as quality, spam, or skip.

quality = substantive, insightful content including but not limited to:
- Product thinking, design decisions, user insights
- Engineering practices, project experiences, lessons learned
- Business analysis, market observations, startup strategy
- Thoughtful reflections on AI agents, LLMs, their future
- Founder stories with real substance

spam = discard immediately:
- Marketing/promotion/product launches framed as ads
- Emotional venting, hot takes with no substance
- Hype without content ("this is the future!")
- Self-promotion disguised as insight
- Giveaways, airdrops, follow-for-follow
- Filler content ("gm", "just shipped X", mindless hype)

skip = everything else (news, personal updates, opinion without insight)

Be strict. If unsure between quality and skip, default to skip.
If unsure between spam and skip, default to skip.

Tweets:
{tweets_text}

Reply with a JSON array ONLY — one object per tweet in the same order, no other text:
[{{"id": 0, "verdict": "quality"}}, {{"id": 1, "verdict": "spam"}}, ...]"""


def classify_tweets(tweets: list) -> list:
    if not tweets:
        return tweets

    tweet_lines = []
    for i, t in enumerate(tweets):
        handle = t.get("handle", "?")
        text = t.get("text", "").replace("\n", " ")[:300]
        tweet_lines.append(f"[{i}] @{handle}: {text}")

    prompt = PROMPT_TEMPLATE.format(tweets_text="\n".join(tweet_lines))

    try:
        result = subprocess.run(
            ["codex", "exec", "--model", MODEL, prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"codex error (code {result.returncode}): {result.stderr[:200]}", file=sys.stderr)
            raise RuntimeError("codex failed")
    except subprocess.TimeoutExpired:
        print("codex timed out", file=sys.stderr)
        raise
    except FileNotFoundError:
        print("codex CLI not found in PATH", file=sys.stderr)
        raise

    # codex exec outputs a header + model responses + "tokens used\nN\nLAST_RESPONSE"
    # Extract the JSON array from stdout — find the last [...] block
    raw_out = result.stdout

    # Strip markdown code fences if present
    content = raw_out
    if "```" in content:
        parts = content.split("```")
        for part in parts:
            stripped = part.strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
            if stripped.startswith("["):
                content = stripped
                break
    else:
        # Find the last occurrence of a JSON array in the output
        last_bracket = content.rfind("[")
        if last_bracket != -1:
            content = content[last_bracket:]
            # Trim trailing noise after the closing ]
            last_close = content.rfind("]")
            if last_close != -1:
                content = content[:last_close + 1]

    try:
        verdicts = json.loads(content)
        verdict_map = {v["id"]: v["verdict"] for v in verdicts}
    except Exception as e:
        print(f"Failed to parse codex response: {e}\nRaw: {content[:300]}", file=sys.stderr)
        raise

    for i, t in enumerate(tweets):
        t["verdict"] = verdict_map.get(i, "skip")

    return tweets


def main():
    raw = sys.stdin.read()
    tweets = json.loads(raw)

    MIN_LEN = 30
    valid = [t for t in tweets if len(t.get("text", "")) >= MIN_LEN]
    short = [dict(t, verdict="skip") for t in tweets if len(t.get("text", "")) < MIN_LEN]

    print(f"Classifying {len(valid)} tweets (skipping {len(short)} too short)...", file=sys.stderr)

    try:
        classified = classify_tweets(valid)
    except Exception:
        print("Classification failed, marking all as skip", file=sys.stderr)
        classified = [dict(t, verdict="skip") for t in valid]

    all_tweets = classified + short

    counts = {"quality": 0, "spam": 0, "skip": 0}
    for t in all_tweets:
        counts[t.get("verdict", "skip")] += 1
    print(f"Results — quality: {counts['quality']}, spam: {counts['spam']}, skip: {counts['skip']}", file=sys.stderr)

    print(json.dumps(all_tweets, ensure_ascii=False))


if __name__ == "__main__":
    main()
