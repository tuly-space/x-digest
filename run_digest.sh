#!/bin/bash
# X/Twitter Hourly Digest — scrape, filter, mark not-interested, archive, push to repo
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

# Step 2: Mark off-topic tweets as "Not interested" (max 3, with delays)
echo "$RAW" | (cd "$DIR" && uv run --with playwright python mark_not_interested.py) 2>&1 || true

# Step 3: Filter and format digest
DIGEST=$(echo "$RAW" | (cd "$DIR" && uv run python filter_digest.py) 2>/dev/null)

if [ -z "$DIGEST" ]; then
    echo "Empty digest after filtering at $TIMESTAMP" >&2
    exit 1
fi

# Step 4: Save to file
OUTFILE="$DIGEST_DIR/${DATE}_${HOUR}.md"
{
    echo "# X Digest — $DATE ${HOUR}:00 UTC"
    echo ""
    echo "$DIGEST"
} > "$OUTFILE"

# Step 5: Push to repo
cd "$DIR"
git add "digests/${DATE}_${HOUR}.md"
git commit -m "digest: ${DATE} ${HOUR}:00 UTC" --quiet 2>/dev/null || true
git push origin main --quiet 2>/dev/null || git push origin master --quiet 2>/dev/null || true

# Step 6: Output digest for delivery
echo "$DIGEST"
