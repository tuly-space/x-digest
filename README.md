# X Digest

Automated hourly digest from Twitter/X "For You" timeline — scrape, LLM-classify, deduplicate, deliver to Discord.

## How it works

Each hourly run opens a single Playwright session and does three things **in one pass**:

1. **Scrape** — scroll the For You timeline screen by screen
2. **Classify** — batch LLM-classify each screen's tweets (`codex exec gpt-5.4-mini`)
3. **Mark** — immediately flag spam tweets as "Not interested" while still in DOM

Then:

4. **Follow** — auto-follow quality tweet authors not yet followed (max 5/run)
5. **Filter + deduplicate** — keep only `verdict=quality`, skip already-seen links
6. **Archive** — save digest to `digests/YYYY-MM-DD_HH.md`, push to git
7. **Deliver** — post as a new thread in Discord forum `#tweets`

The scrape→classify→mark interleaving is intentional: X removes off-screen DOM nodes on scroll, so you can't scrape everything first and mark later.

## Structure

```
scrape_and_process.py    # Core: scrape + classify + mark (interleaved)
auto_follow.py           # Auto-follow quality authors
filter_digest.py         # Keep quality tweets, dedup, rank, format
run_digest.sh            # Orchestrator (cron entry point)
seen_links.txt           # Cross-run dedup state (local, not in git)
digests/                 # Hourly digest archive (git tracked)
```

## Running manually

```bash
cd projects/x-digest
bash run_digest.sh
```

Requires: Chrome running at `localhost:18800` with X logged in (`~/chrome-profile`), and `codex` CLI available.

## Quality criteria (LLM judge)

**Keep (quality):**
- Product thinking, design decisions, user insights
- Engineering practices, lessons learned
- Business analysis, market observations, startup strategy
- Thoughtful takes on AI agents / LLMs
- Founder stories with real substance

**Discard (spam):** Marketing, emotional venting, hype with no content, giveaways, filler.

## License

Private — tuly-space internal use.
