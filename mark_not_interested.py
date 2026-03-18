"""
Mark spam tweets as "Not interested in this post" on X/Twitter.
Must operate on the For You timeline — the option is NOT available on tweet detail pages.

Strategy:
- Navigate to x.com/home (For You tab)
- Scroll timeline, collect visible articles
- For each article whose link matches a spam tweet, click its "..." → "Not interested in this post"

Reads classified JSON from stdin (with `verdict` field from llm_classify.py).
"""
import asyncio
import json
import random
import sys
from playwright.async_api import async_playwright

MAX_MARKS_PER_RUN = 5
SCROLL_ROUNDS = 20
SCROLL_PX = 800
SCROLL_WAIT_MS = 1500


async def main():
    raw = sys.stdin.read()
    tweets = json.loads(raw)

    spam_links = {
        t["link"].rstrip("/")
        for t in tweets
        if t.get("verdict") == "spam" and t.get("link")
    }

    if not spam_links:
        print("No spam tweets to mark.", file=sys.stderr)
        return

    print(f"Will try to mark {min(len(spam_links), MAX_MARKS_PER_RUN)}/{len(spam_links)} spam tweets on timeline", file=sys.stderr)

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:18800")
        context = browser.contexts[0]
        page = await context.new_page()

        try:
            await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # Make sure we're on "For you" tab
            try:
                for_you = page.locator('a[role="tab"]:has-text("For you")')
                if await for_you.count() > 0:
                    await for_you.click()
                    await page.wait_for_timeout(2000)
            except Exception:
                pass

            marked = 0
            remaining = set(spam_links)

            for scroll_round in range(SCROLL_ROUNDS):
                if marked >= MAX_MARKS_PER_RUN or not remaining:
                    break

                # Find all tweet articles currently in DOM
                articles = await page.locator('article[data-testid="tweet"]').all()

                for article in articles:
                    if marked >= MAX_MARKS_PER_RUN or not remaining:
                        break

                    try:
                        link_el = article.locator('a[href*="/status/"]').first
                        if await link_el.count() == 0:
                            continue
                        href = await link_el.get_attribute("href")
                        if not href:
                            continue
                        full_link = ("https://x.com" + href).rstrip("/")

                        if full_link not in remaining:
                            continue

                        # Scroll article into view
                        await article.scroll_into_view_if_needed()
                        await page.wait_for_timeout(500)

                        # Click the "..." caret on this article
                        caret = article.locator('[data-testid="caret"]').first
                        if await caret.count() == 0:
                            print(f"  No caret for {full_link}", file=sys.stderr)
                            continue

                        await caret.click()
                        await page.wait_for_timeout(1200)

                        # Look for "Not interested in this post"
                        menu_items = page.locator('[role="menuitem"]')
                        count = await menu_items.count()
                        found = False
                        for i in range(count):
                            item = menu_items.nth(i)
                            text = await item.inner_text()
                            if "not interested" in text.lower():
                                await item.click()
                                marked += 1
                                remaining.discard(full_link)
                                handle = next(
                                    (t.get("handle", "?") for t in tweets if t.get("link", "").rstrip("/") == full_link),
                                    "?"
                                )
                                print(f"  ✓ Marked @{handle} as not interested ({full_link})", file=sys.stderr)
                                found = True
                                await page.wait_for_timeout(random.randint(3000, 7000))
                                break

                        if not found:
                            await page.keyboard.press("Escape")
                            await page.wait_for_timeout(500)
                            print(f"  'Not interested' not in menu for {full_link}", file=sys.stderr)
                            # Don't retry this one
                            remaining.discard(full_link)

                    except Exception as e:
                        print(f"  Error on article: {e}", file=sys.stderr)
                        try:
                            await page.keyboard.press("Escape")
                        except Exception:
                            pass

                # Scroll down to load more tweets
                await page.evaluate(f"window.scrollBy(0, {SCROLL_PX})")
                await page.wait_for_timeout(SCROLL_WAIT_MS)

            print(f"\nMarked {marked}/{min(len(spam_links), MAX_MARKS_PER_RUN)} tweets as not interested.", file=sys.stderr)

        finally:
            await page.close()


asyncio.run(main())
