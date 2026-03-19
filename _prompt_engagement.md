# Task: Refactor x-digest filtering logic

Implement the new filtering priority in the x-digest pipeline.

## New filter logic (priority order)

```
① Session-level dedup (same tweet appears twice in one run) → discard
② likes > 100 → verdict = "quality_hot" (bypass LLM entirely)
③ Otherwise → LLM classify → quality / spam / skip
```

For "quality_hot" tweets:
- Auto-like: YES (same as LLM quality)
- Auto-follow: NO (no LLM topic check, so don't follow)
- digest: YES (included in digest output)

## Changes required

### 1. `scrape_and_process.py`

In the `main()` function, after extracting `new_tweets`, before calling `classify_batch()`:

1. **Session dedup is already handled** by `seen_links` set — no change needed there.

2. **Add engagement pre-check** before sending to LLM:
   ```python
   LIKES_HOT_THRESHOLD = 100
   
   hot_tweets = [t for t in new_tweets if t.get("likes", 0) > LIKES_HOT_THRESHOLD]
   llm_tweets = [t for t in new_tweets if t.get("likes", 0) <= LIKES_HOT_THRESHOLD]
   
   # Mark hot tweets without LLM
   for t in hot_tweets:
       t["verdict"] = "quality_hot"
   
   # Classify rest with LLM
   classified_llm = classify_batch(llm_tweets) if llm_tweets else []
   
   classified = hot_tweets + classified_llm
   ```

3. **Auto-like logic**: change the quality_batch filter to include both "quality" AND "quality_hot":
   ```python
   quality_batch = [t for t in classified if t.get("verdict") in ("quality", "quality_hot")]
   ```

4. **Stats counting**: count "quality_hot" separately in the counts dict. Add `counts["quality_hot"] = 0` at init. In the counts loop: `counts[t.get("verdict", "skip")] += 1` will handle it automatically if "quality_hot" is added to dict.

5. **Update print statement** at the end to include quality_hot count.

### 2. `filter_digest.py`

In the `main()` function, change the verdict filter:

```python
# Old: only pass "quality"
if t['verdict'] != 'quality':
    continue

# New: pass "quality" and "quality_hot"
if t['verdict'] not in ('quality', 'quality_hot'):
    continue
```

Also:
- **Remove `seen_links` persistence** (`load_seen_links`, `save_seen_links`, `--seen-file` arg). Since For You rarely repeats tweets, and scrape_and_process already handles session dedup, cross-run dedup is no longer needed.
- Remove the `dropped_seen` tracking and related stderr output.
- Keep `--output json` and `--output markdown` modes.

### 3. `auto_follow.py`

No change to the script itself. But in `run_digest.sh`, auto_follow should only be fed LLM-quality tweets, not quality_hot ones. The cleanest way: after filtering, pipe only tweets with `verdict == "quality"` to auto_follow.

Actually — auto_follow.py reads the full classified JSON and follows quality authors. Simplest fix: in auto_follow.py, change the quality check to only follow `verdict == "quality"` (not `quality_hot`). Check the current filter condition in auto_follow.py and make sure it's `== "quality"` not `in ("quality", ...)`.

### 4. `run_digest.sh`

- Remove `--seen-file` argument from the `filter_digest.py` call (seen_links.txt no longer used).
- Remove `SEEN_FILE="$DIR/seen_links.txt"` line.

## Important

- Do NOT change the LLM classify prompt.
- Do NOT change scroll rounds, like limits, mark limits.
- Do NOT change the Discord delivery format.
- Preserve all existing error handling.

When completely finished, run: openclaw system event --text "Done: x-digest engagement pre-filter implemented" --mode now
