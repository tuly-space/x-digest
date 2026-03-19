#!/bin/bash
# X/Twitter Hourly Digest — scrape+classify+mark (interleaved) → follow → filter → archive → push
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
DIGEST_DIR="$DIR/digests"
mkdir -p "$DIGEST_DIR"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
DATE=$(date -u +"%Y-%m-%d")
HOUR=$(date -u +"%H")

# Step 1-2-4 (interleaved): Scrape + LLM classify + mark "Not interested" in one pass
# Each screen is classified and spam-marked before scrolling away.
# scrape_and_process.py: JSON on stdout, progress on stderr.
CLASSIFIED=$(cd "$DIR" && uv run --with playwright python scrape_and_process.py 2>/dev/null)

if [ -z "$CLASSIFIED" ] || [ "$CLASSIFIED" = "[]" ]; then
    echo "No tweets from scrape_and_process at $TIMESTAMP" >&2
    exit 1
fi

# Step 3: Auto-follow quality tweet authors; capture newly followed handles
NEW_FOLLOWS=$(echo "$CLASSIFIED" | (cd "$DIR" && uv run --with playwright python auto_follow.py) 2>/dev/null || true)

# Step 5: Filter to quality tweets (JSON output for summarization)
SEEN_FILE="$DIR/seen_links.txt"
FILTERED_JSON=$(echo "$CLASSIFIED" | (cd "$DIR" && uv run python filter_digest.py --seen-file "$SEEN_FILE" --output json) 2>/dev/null)

if [ -z "$FILTERED_JSON" ] || [ "$FILTERED_JSON" = "[]" ]; then
    echo "Empty digest after filtering at $TIMESTAMP" >&2
    exit 1
fi

# Step 5b: Summarize via codex exec gpt-5.4-mini (one-line summary per tweet)
DIGEST=$(echo "$FILTERED_JSON" | (cd "$DIR" && uv run python summarize_digest.py) 2>/dev/null)

if [ -z "$DIGEST" ]; then
    echo "Summarization failed at $TIMESTAMP" >&2
    exit 1
fi

# Step 6: Save to file
OUTFILE="$DIGEST_DIR/${DATE}_${HOUR}.md"
{
    echo "# X Digest — $DATE ${HOUR}:00 UTC"
    echo ""
    echo "$DIGEST"
} > "$OUTFILE"

# Step 7: Push to repo (via jj)
cd "$DIR"
JJ=~/.local/bin/jj
$JJ describe -m "digest: ${DATE} ${HOUR}:00 UTC" 2>/dev/null || true
$JJ new 2>/dev/null || true
$JJ git push --bookmark main 2>/dev/null || true

# Step 8: Output digest (+ new follows) for delivery
echo "$DIGEST"
if [ -n "$NEW_FOLLOWS" ]; then
    echo ""
    echo "---"
    echo "**新关注：** $NEW_FOLLOWS"
fi
