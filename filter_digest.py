"""
Filter and rank tweets for the digest.
Reads JSON from stdin (output of scrape_timeline.py), prints filtered digest as markdown.

Filtering rules:
- Drop tweets with no text or very short text (<30 chars)
- Drop obvious promo/spam patterns
- Drop low-engagement tweets (configurable threshold)
- Rank by a combination of recency and engagement
- Deduplicate: skip tweets already seen in previous runs (tracked via --seen-file)

Usage:
    python scrape_timeline.py | python filter_digest.py [--seen-file path/to/seen_links.txt]
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

# Patterns for filtering out noise
SPAM_PATTERNS = [
    r'(?i)giveaway|airdrop|whitelist|drop your wallet',
    r'(?i)^(gm|gn|good morning|good night)[!.]*$',
    r'(?i)follow me|follow back|f4f',
    r'(?i)subscribe to my|check out my link|use my code',
    r'(?i)limited time offer|act now|don\'t miss',
]

# Relevance filter: tweet must match at least one of these to be kept
AI_RELEVANCE_PATTERNS = [
    r'(?i)\bAI\b', r'(?i)\bartificial intelligence\b',
    r'(?i)\bLLM\b', r'(?i)\blarge language model\b',
    r'(?i)\bGPT[-\s]?\d', r'(?i)\bclaude\b', r'(?i)\bgemini\b',
    r'(?i)\bagent[s]?\b', r'(?i)\bagentic\b',
    r'(?i)\bmachine learning\b', r'(?i)\bdeep learning\b',
    r'(?i)\bneural\b', r'(?i)\btransformer\b',
    r'(?i)\bfine.?tun', r'(?i)\bprompt\b',
    r'(?i)\bRAG\b', r'(?i)\bembedding\b',
    r'(?i)\btoken[s]?\b', r'(?i)\binference\b',
    r'(?i)\bfoundation model\b', r'(?i)\bopen.?source\b',
    r'(?i)\bmodel[s]?\b',
    r'(?i)\bSaaS\b', r'(?i)\bstartup\b', r'(?i)\bYC\b',
    r'(?i)\bfunding\b', r'(?i)\bseries [A-D]\b',
    r'(?i)\bcoding\b', r'(?i)\bdev tool', r'(?i)\bdeveloper\b',
    r'(?i)\bautomation\b', r'(?i)\bworkflow\b',
    r'(?i)\bcompute\b', r'(?i)\bGPU\b', r'(?i)\bTPU\b',
    r'(?i)\bchip\b', r'(?i)\brobot', r'(?i)\bhardware\b',
    r'(?i)\bOpenAI\b', r'(?i)\bAnthropic\b',
    r'(?i)\bcodex\b', r'(?i)\bcopilot\b', r'(?i)\bcursor\b',
    r'(?i)\bAPI\b', r'(?i)\bsdk\b',
    r'(?i)\bvector\b', r'(?i)\bdiffusion\b',
    r'(?i)\bscale\b.*\b(AI|model|infra)',
    r'(?i)\bARC[-\s]?AGI', r'(?i)\bbenchmark\b',
    r'(?i)\breinforcement learning\b', r'(?i)\bRLHF\b',
    r'(?i)\bmultimodal\b', r'(?i)\bvision model\b',
    r'(?i)\bcontext window\b', r'(?i)\breasoning\b',
]

MIN_TEXT_LEN = 30


def is_ai_relevant(text: str) -> bool:
    """Check if tweet is related to AI/LLM/tech topics."""
    for pattern in AI_RELEVANCE_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def parse_engagement(val: str) -> int:
    """Parse engagement string like '1.2K' to int."""
    val = val.strip()
    if not val:
        return 0
    val = val.replace(',', '')
    if val.endswith('K'):
        return int(float(val[:-1]) * 1000)
    if val.endswith('M'):
        return int(float(val[:-1]) * 1000000)
    try:
        return int(val)
    except ValueError:
        return 0


def is_spam(text: str) -> bool:
    for pattern in SPAM_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def score_tweet(tweet: dict) -> float:
    """Higher = more interesting."""
    likes = parse_engagement(tweet.get('likes', '0'))
    retweets = parse_engagement(tweet.get('retweets', '0'))
    replies = parse_engagement(tweet.get('replies', '0'))
    
    engagement = likes + retweets * 3 + replies * 2
    
    # Text length bonus (longer = more substantive, up to a point)
    text_len = len(tweet.get('text', ''))
    length_bonus = min(text_len / 280, 1.5)
    
    return engagement * length_bonus


def format_digest(tweets: list) -> str:
    """Format filtered tweets as markdown digest."""
    if not tweets:
        return "No notable tweets found this hour."
    
    lines = []
    for i, t in enumerate(tweets, 1):
        handle = t.get('handle', '?')
        text = t.get('text', '').replace('\n', '\n> ')
        link = t.get('link', '')
        likes = t.get('likes', '0')
        retweets = t.get('retweets', '0')
        
        lines.append(f"**{i}. @{handle}** — ❤️{likes} 🔁{retweets}")
        lines.append(f"> {text}")
        if link:
            lines.append(f"> {link}")
        lines.append("")
    
    return "\n".join(lines)


def load_seen_links(path: str) -> set:
    """Load previously seen tweet links from file."""
    if not path or not os.path.exists(path):
        return set()
    with open(path, 'r') as f:
        return {line.strip() for line in f if line.strip()}


def save_seen_links(path: str, links: list):
    """Append new links to the seen file."""
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'a') as f:
        for link in links:
            f.write(link + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seen-file', default='', help='Path to file tracking seen tweet links (for deduplication)')
    args = parser.parse_args()

    raw = sys.stdin.read()
    tweets = json.loads(raw)

    # Load previously seen links
    seen_links = load_seen_links(args.seen_file)

    # Filter
    filtered = []
    dropped_seen = 0
    for t in tweets:
        text = t.get('text', '')
        link = t.get('link', '')
        # If LLM verdict is present, use it (only keep "quality")
        if 'verdict' in t:
            if t['verdict'] != 'quality':
                continue
        else:
            # Fallback: basic rule-based filter
            if len(text) < MIN_TEXT_LEN:
                continue
            if is_spam(text):
                continue
        # Dedup: skip already-seen tweets
        if link and link in seen_links:
            dropped_seen += 1
            continue
        filtered.append(t)

    # Score and rank
    for t in filtered:
        t['_score'] = score_tweet(t)

    filtered.sort(key=lambda x: x['_score'], reverse=True)

    # Take top 30
    top = filtered[:30]

    # Persist seen links for next run
    new_links = [t['link'] for t in top if t.get('link')]
    save_seen_links(args.seen_file, new_links)

    # Output
    digest = format_digest(top)
    print(digest)

    # Also output stats to stderr
    print(
        f"\n---\nTotal scraped: {len(tweets)} | Dropped seen (dedup): {dropped_seen} "
        f"| After filter: {len(filtered)} | Showing top: {len(top)}",
        file=sys.stderr
    )


if __name__ == '__main__':
    main()
