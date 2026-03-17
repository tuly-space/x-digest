"""
Mark off-topic tweets as "Not interested" on X/Twitter.
Reads JSON from stdin (full scraped tweets), identifies non-AI/LLM tweets,
and clicks "Not interested" on them via browser automation.

Safety:
- Max 3 marks per run to avoid rate limiting / bot detection
- Random delays between actions (5-15 seconds)
- Only marks tweets clearly unrelated to AI/LLM/tech
"""
import asyncio
import json
import random
import re
import sys
from playwright.async_api import async_playwright

MAX_MARKS_PER_RUN = 3

# Keywords that indicate AI/LLM/tech relevance — keep these
RELEVANT_PATTERNS = [
    r'(?i)\bAI\b', r'(?i)\bartificial intelligence\b',
    r'(?i)\bLLM\b', r'(?i)\blarge language model\b',
    r'(?i)\bGPT\b', r'(?i)\bclaude\b', r'(?i)\bgemini\b',
    r'(?i)\bagent\b', r'(?i)\bagentic\b',
    r'(?i)\bmachine learning\b', r'(?i)\bML\b',
    r'(?i)\bdeep learning\b', r'(?i)\bneural\b',
    r'(?i)\btransformer\b', r'(?i)\bdiffusion\b',
    r'(?i)\bfine.?tun\b', r'(?i)\bprompt\b',
    r'(?i)\bRAG\b', r'(?i)\bvector\b', r'(?i)\bembedding\b',
    r'(?i)\btoken\b', r'(?i)\binference\b',
    r'(?i)\bmodel\b', r'(?i)\bfoundation model\b',
    r'(?i)\bopen.?source\b', r'(?i)\bAPI\b',
    r'(?i)\bSaaS\b', r'(?i)\bstartup\b', r'(?i)\bYC\b',
    r'(?i)\bfunding\b', r'(?i)\bseries [A-D]\b',
    r'(?i)\bproduct\b', r'(?i)\bship\b', r'(?i)\blaunch\b',
    r'(?i)\bcoding\b', r'(?i)\bdev\b', r'(?i)\bengineer\b',
    r'(?i)\btech\b', r'(?i)\bsoftware\b',
    r'(?i)\bautomation\b', r'(?i)\bworkflow\b',
    r'(?i)\bcloud\b', r'(?i)\binfra\b',
    r'(?i)\bscale\b', r'(?i)\bcompute\b',
    r'(?i)\bchip\b', r'(?i)\bGPU\b', r'(?i)\bTPU\b',
    r'(?i)\brobot\b', r'(?i)\bhardware\b',
    r'(?i)\bOpenAI\b', r'(?i)\bAnthropic\b', r'(?i)\bGoogle\b',
    r'(?i)\bMeta\b', r'(?i)\bMicrosoft\b', r'(?i)\bApple\b',
]


def is_relevant(text: str) -> bool:
    """Check if tweet text is related to AI/LLM/tech."""
    for pattern in RELEVANT_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


async def main():
    raw = sys.stdin.read()
    tweets = json.loads(raw)

    # Find off-topic tweets
    off_topic = [t for t in tweets if not is_relevant(t.get('text', ''))]

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
