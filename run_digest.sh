#!/bin/bash
# X/Twitter Hourly Digest — scrape → LLM classify → filter → follow → mark spam → archive → push
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
DIGEST_DIR="$DIR/digests"
mkdir -p "$DIGEST_DIR"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
DATE=$(date -u +"%Y-%m-%d")
HOUR=$(date -u +"%H")

# Step 1: Scrape timeline
RAW=$(cd "$DIR" && uv run --with playwright python scrape_timeline.py 2>/dev/null)

if [ -z "$RAW" ] || [ "$RAW" = "[]" ]; then
    echo "No tweets scraped at $TIMESTAMP" >&2
    exit 1
fi

# Step 2: LLM classify (haiku via OpenRouter)
CLASSIFIED=$(echo "$RAW" | (cd "$DIR" && uv run python llm_classify.py) 2>/dev/null)

if [ -z "$CLASSIFIED" ]; then
    echo "LLM classification failed, falling back to raw" >&2
    CLASSIFIED="$RAW"
fi

# Step 3: Auto-follow quality tweet authors
echo "$CLASSIFIED" | (cd "$DIR" && uv run --with playwright python auto_follow.py) 2>&1 || true

# Step 4: Mark spam tweets as "Not interested"
echo "$CLASSIFIED" | (cd "$DIR" && uv run --with playwright python mark_not_interested.py) 2>&1 || true

# Step 5: Filter and format digest (only quality tweets, dedup across runs)
SEEN_FILE="$DIR/seen_links.txt"
DIGEST=$(echo "$CLASSIFIED" | (cd "$DIR" && uv run python filter_digest.py --seen-file "$SEEN_FILE") 2>/dev/null)

if [ -z "$DIGEST" ]; then
    echo "Empty digest after filtering at $TIMESTAMP" >&2
    exit 1
fi

# Step 6: Save to file
OUTFILE="$DIGEST_DIR/${DATE}_${HOUR}.md"
{
    echo "# X Digest — $DATE ${HOUR}:00 UTC"
    echo ""
    echo "$DIGEST"
} > "$OUTFILE"

# Step 7: Push to repo
cd "$DIR"
git add "digests/${DATE}_${HOUR}.md"
git commit -m "digest: ${DATE} ${HOUR}:00 UTC" --quiet 2>/dev/null || true
git push origin main --quiet 2>/dev/null || git push origin master --quiet 2>/dev/null || true

# Step 8: Output digest for delivery
echo "$DIGEST"
