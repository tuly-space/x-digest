# X Digest

Automated hourly digest of AI/LLM-related content from Twitter/X "For You" timeline.

## How it works

1. **Scrape** — Playwright connects to a logged-in Chrome session, scrolls the For You timeline
2. **Filter** — Drops spam, promo, low-effort, and off-topic (non-AI/LLM) tweets
3. **Rank** — Scores by engagement × content depth
4. **Deliver** — Top posts sent to Discord, archived as markdown in `digests/`
5. **Train** — Off-topic tweets get "Not interested" feedback on X to improve the algorithm

## Structure

```
digests/
  YYYY-MM-DD_HH.md    # Hourly digest archive
scrape_timeline.py     # Timeline scraper
filter_digest.py       # Quality filter + ranker
mark_not_interested.py # Auto-mark off-topic tweets
run_digest.sh          # Orchestrator
```

## License

Private — tuly-space internal use.
