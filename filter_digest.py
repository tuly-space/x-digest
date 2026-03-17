"""
Filter and rank tweets for the digest.
Reads JSON from stdin (output of scrape_timeline.py), prints filtered digest as markdown.

Filtering rules:
- Drop tweets with no text or very short text (<30 chars)
- Drop obvious promo/spam patterns
- Drop low-engagement tweets (configurable threshold)
- Rank by a combination of recency and engagement
"""
import json
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

MIN_TEXT_LEN = 30


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


def main():
    raw = sys.stdin.read()
    tweets = json.loads(raw)
    
    # Filter
    filtered = []
    for t in tweets:
        text = t.get('text', '')
        if len(text) < MIN_TEXT_LEN:
            continue
        if is_spam(text):
            continue
        filtered.append(t)
    
    # Score and rank
    for t in filtered:
        t['_score'] = score_tweet(t)
    
    filtered.sort(key=lambda x: x['_score'], reverse=True)
    
    # Take top 15
    top = filtered[:15]
    
    # Output
    digest = format_digest(top)
    print(digest)
    
    # Also output stats to stderr
    print(f"\n---\nTotal scraped: {len(tweets)} | After filter: {len(filtered)} | Showing top: {len(top)}", file=sys.stderr)


if __name__ == '__main__':
    main()
