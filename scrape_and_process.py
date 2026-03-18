"""
X/Twitter For You Timeline — Interleaved Scrape + Classify + Mark

Strategy:
  for each scroll screen:
    1. extract newly-visible tweet articles from DOM
    2. batch-classify them via LLM (codex exec)
    3. immediately mark spam ones as "Not interested" (still in viewport)
    4. scroll down

Outputs a JSON array of all classified tweets to stdout at the end.
Stderr: progress / stats.

Why interleaved: tweets scroll out of the DOM on re-render. If we scrape
everything first and then try to mark, the target articles are gone.
"""
import asyncio
import json
import random
import subprocess
import sys
from playwright.async_api import async_playwright

SCROLL_ROUNDS = 15
SCROLL_PX = 900
SCROLL_WAIT_MS = 1800
MAX_MARKS_PER_RUN = 5
LLM_MODEL = "gpt-5.4-mini"
MIN_TEXT_LEN = 30

# ---------- LLM ----------

CLASSIFY_PROMPT = """You are a strict curator for a high-signal Twitter digest.
Classify each tweet as quality, spam, or skip.

quality = substantive, insightful content:
- Product thinking, design decisions, user insights
- Engineering practices, project experiences, lessons learned
- Business analysis, market observations, startup strategy
- Thoughtful reflections on AI agents, LLMs, their future
- Founder stories with real substance

spam = discard immediately:
- Marketing/promotion framed as ads
- Emotional venting, hot takes with no substance
- Hype without content ("this is the future!")
- Self-promotion disguised as insight
- Giveaways, follow-for-follow
- Filler ("gm", "just shipped X", mindless hype)

skip = everything else

Be strict. If unsure between quality and skip → skip.
If unsure between spam and skip → skip.

Tweets:
{tweets_text}

Reply with JSON array ONLY:
[{{"id": 0, "verdict": "quality"}}, {{"id": 1, "verdict": "spam"}}, ...]"""


def classify_batch(tweets: list) -> list:
    """Classify a batch of tweets. Returns tweets with 'verdict' field added."""
    if not tweets:
        return tweets

    valid = [t for t in tweets if len(t.get("text", "")) >= MIN_TEXT_LEN]
    short = [dict(t, verdict="skip") for t in tweets if len(t.get("text", "")) < MIN_TEXT_LEN]

    if not valid:
        return short

    lines = [f"[{i}] @{t.get('handle','?')}: {t.get('text','').replace(chr(10),' ')[:280]}"
             for i, t in enumerate(valid)]
    prompt = CLASSIFY_PROMPT.format(tweets_text="\n".join(lines))

    try:
        result = subprocess.run(
            ["codex", "exec", "--model", LLM_MODEL, prompt],
            capture_output=True, text=True, timeout=60,
        )
        raw = result.stdout

        # Strip markdown fences
        content = raw
        if "```" in content:
            for part in content.split("```"):
                s = part.strip().lstrip("json").strip()
                if s.startswith("["):
                    content = s
                    break
        else:
            lb = content.rfind("[")
            if lb != -1:
                content = content[lb:]
                rb = content.rfind("]")
                if rb != -1:
                    content = content[:rb + 1]

        verdicts = json.loads(content)
        vmap = {v["id"]: v["verdict"] for v in verdicts}
        for i, t in enumerate(valid):
            t["verdict"] = vmap.get(i, "skip")
    except Exception as e:
        print(f"  [classify] error: {e}", file=sys.stderr)
        for t in valid:
            t["verdict"] = "skip"

    return valid + short


# ---------- DOM helpers ----------

EXTRACT_JS = """
(existingLinks) => {
    const articles = document.querySelectorAll('article[data-testid="tweet"]');
    const results = [];
    const seen = new Set(existingLinks);
    for (const article of articles) {
        try {
            const userEl = article.querySelector('[data-testid="User-Name"]');
            const textEl = article.querySelector('[data-testid="tweetText"]');
            const timeEl = article.querySelector('time');
            const linkEl = article.querySelector('a[href*="/status/"]');
            const likeEl  = article.querySelector('[data-testid="like"]');
            const rtEl    = article.querySelector('[data-testid="retweet"]');

            const href = linkEl ? linkEl.getAttribute('href') : '';
            if (!href || seen.has(href)) continue;
            seen.add(href);

            const rawUser = userEl ? userEl.textContent.trim() : '';
            const pathParts = href.split('/').filter(Boolean);
            const handle  = pathParts.length >= 1 ? pathParts[0] : (rawUser.split('@').pop() || '').trim();
            const text    = textEl ? textEl.innerText.trim() : '';
            const ts      = timeEl ? timeEl.getAttribute('datetime') : '';
            const likes   = likeEl ? (parseInt(likeEl.getAttribute('aria-label') || '0') || 0) : 0;
            const rts     = rtEl   ? (parseInt(rtEl.getAttribute('aria-label')   || '0') || 0) : 0;

            results.push({ handle, text, link: 'https://x.com' + href, timestamp: ts, likes, retweets: rts });
        } catch(e) {}
    }
    return results;
}
"""


# ---------- Main ----------

async def main():
    all_tweets = []          # final classified output
    seen_links = set()       # track extracted links across rounds
    total_marked = 0         # "not interested" count this run
    counts = {"quality": 0, "spam": 0, "skip": 0}

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:18800")
        context = browser.contexts[0]
        page = await context.new_page()

        try:
            await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # Switch to "For you" tab
            try:
                tab = page.locator('a[role="tab"]:has-text("For you")')
                if await tab.count() > 0:
                    await tab.click()
                    await page.wait_for_timeout(2000)
            except Exception:
                pass

            for round_i in range(SCROLL_ROUNDS):
                # ── 1. Extract newly-visible tweets ──
                new_tweets = await page.evaluate(EXTRACT_JS, list(seen_links))
                for t in new_tweets:
                    seen_links.add(t["link"].replace("https://x.com", ""))

                if not new_tweets:
                    await page.evaluate(f"window.scrollBy(0, {SCROLL_PX})")
                    await page.wait_for_timeout(SCROLL_WAIT_MS)
                    continue

                print(f"[round {round_i+1}] scraped {len(new_tweets)} new tweets", file=sys.stderr)

                # ── 2. Classify this batch ──
                classified = classify_batch(new_tweets)
                for t in classified:
                    counts[t.get("verdict", "skip")] += 1
                all_tweets.extend(classified)

                spam_batch = [t for t in classified if t.get("verdict") == "spam"]
                print(f"[round {round_i+1}] quality={sum(1 for t in classified if t['verdict']=='quality')} spam={len(spam_batch)}", file=sys.stderr)

                # ── 3. Mark spam tweets — they're still visible in DOM ──
                for tweet in spam_batch:
                    if total_marked >= MAX_MARKS_PER_RUN:
                        break
                    link_path = tweet["link"].replace("https://x.com", "")

                    try:
                        # Find the article still in DOM
                        articles = await page.locator('article[data-testid="tweet"]').all()
                        target = None
                        for art in articles:
                            lel = art.locator(f'a[href="{link_path}"]').first
                            if await lel.count() > 0:
                                target = art
                                break

                        if target is None:
                            print(f"  [mark] article gone for @{tweet['handle']}", file=sys.stderr)
                            continue

                        await target.scroll_into_view_if_needed()
                        await page.wait_for_timeout(400)

                        caret = target.locator('[data-testid="caret"]').first
                        if await caret.count() == 0:
                            continue
                        await caret.click()
                        await page.wait_for_timeout(1000)

                        items = page.locator('[role="menuitem"]')
                        n = await items.count()
                        found = False
                        for j in range(n):
                            item = items.nth(j)
                            text = await item.inner_text()
                            if "not interested" in text.lower():
                                await item.click()
                                total_marked += 1
                                print(f"  [mark] ✓ @{tweet['handle']} not interested ({total_marked}/{MAX_MARKS_PER_RUN})", file=sys.stderr)
                                found = True
                                await page.wait_for_timeout(random.randint(2000, 4000))
                                break

                        if not found:
                            await page.keyboard.press("Escape")
                            await page.wait_for_timeout(400)
                    except Exception as e:
                        print(f"  [mark] error @{tweet['handle']}: {e}", file=sys.stderr)
                        try:
                            await page.keyboard.press("Escape")
                        except Exception:
                            pass

                # ── 4. Scroll to next screen ──
                await page.evaluate(f"window.scrollBy(0, {SCROLL_PX})")
                await page.wait_for_timeout(SCROLL_WAIT_MS)

        finally:
            await page.close()

    print(f"\nDone — total {len(all_tweets)} tweets | quality={counts['quality']} spam={counts['spam']} skip={counts['skip']} | marked={total_marked}", file=sys.stderr)
    print(json.dumps(all_tweets, ensure_ascii=False))


asyncio.run(main())
