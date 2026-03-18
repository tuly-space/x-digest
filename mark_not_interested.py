"""
Mark spam tweets as "Not interested" on X/Twitter.
Reads classified JSON from stdin (with `verdict` field from llm_classify.py).
Marks tweets with verdict="spam" as Not Interested to train the X algorithm.

Safety:
- Max 3 marks per run to avoid rate limiting / bot detection
- Random delays between actions (5-15 seconds)
"""
import asyncio
import json
import random
import sys
from playwright.async_api import async_playwright

MAX_MARKS_PER_RUN = 3


async def main():
    raw = sys.stdin.read()
    tweets = json.loads(raw)

    # Use LLM verdict if available, otherwise skip
    off_topic = [t for t in tweets if t.get('verdict') == 'spam']

    if not off_topic:
        print("No off-topic tweets to mark.", file=sys.stderr)
        return

    to_mark = off_topic[:MAX_MARKS_PER_RUN]
    print(f"Found {len(off_topic)} off-topic tweets, marking {len(to_mark)}", file=sys.stderr)

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:18800")
        context = browser.contexts[0]
        page = await context.new_page()

        marked = 0
        for tweet in to_mark:
            link = tweet.get('link', '')
            if not link:
                continue

            try:
                await page.goto(link, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(3000)

                # Click the "..." (more) button on the tweet
                more_btn = page.locator('article[data-testid="tweet"] [data-testid="caret"]').first
                if await more_btn.count() == 0:
                    print(f"  No caret button found for {link}", file=sys.stderr)
                    continue

                await more_btn.click()
                await page.wait_for_timeout(1500)

                # Look for "Not interested" menu item
                not_interested = page.locator('[role="menuitem"]').filter(has_text="Not interested")
                if await not_interested.count() > 0:
                    await not_interested.click()
                    marked += 1
                    handle = tweet.get('handle', '?')
                    print(f"  Marked @{handle} as not interested: {tweet.get('text', '')[:60]}...", file=sys.stderr)
                else:
                    # Close the menu
                    await page.keyboard.press("Escape")
                    print(f"  'Not interested' option not found for {link}", file=sys.stderr)

                # Random delay to look human
                delay = random.uniform(5, 15)
                await page.wait_for_timeout(int(delay * 1000))

            except Exception as e:
                print(f"  Error marking {link}: {e}", file=sys.stderr)
                continue

        await page.close()
        print(f"\nMarked {marked}/{len(to_mark)} tweets as not interested.", file=sys.stderr)


asyncio.run(main())
