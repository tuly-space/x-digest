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

# Import shared relevance check from filter_digest
# Keywords that indicate AI/LLM/tech relevance — keep these
# (mirrors AI_RELEVANCE_PATTERNS in filter_digest.py)
RELEVANT_PATTERNS = [
    r'(?i)\bAI\b', r'(?i)\bartificial intelligence\b',
    r'(?i)\bLLM\b', r'(?i)\blarge language model\b',
    r'(?i)\bGPT[-\s]?\d', r'(?i)\bclaude\b', r'(?i)\bgemini\b',
    r'(?i)\bagent[s]?\b', r'(?i)\bagentic\b',
    r'(?i)\bmachine learning\b', r'(?i)\bdeep learning\b',
    r'(?i)\bneural\b', r'(?i)\btransformer\b',
    r'(?i)\bfine.?tun', r'(?i)\bprompt\b',
    r'(?i)\bRAG\b', r'(?i)\bembedding\b',
    r'(?i)\btoken[s]?\b', r'(?i)\binference\b',
    r'(?i)\bfoundation model\b', r'(?i)\bopen.?source\b',
    r'(?i)\bmodel[s]?\b',
    r'(?i)\bSaaS\b', r'(?i)\bstartup\b', r'(?i)\bYC\b',
    r'(?i)\bfunding\b', r'(?i)\bseries [A-D]\b',
    r'(?i)\bcoding\b', r'(?i)\bdev tool', r'(?i)\bdeveloper\b',
    r'(?i)\bautomation\b', r'(?i)\bworkflow\b',
    r'(?i)\bcompute\b', r'(?i)\bGPU\b', r'(?i)\bTPU\b',
    r'(?i)\bchip\b', r'(?i)\brobot', r'(?i)\bhardware\b',
    r'(?i)\bOpenAI\b', r'(?i)\bAnthropic\b',
    r'(?i)\bcodex\b', r'(?i)\bcopilot\b', r'(?i)\bcursor\b',
    r'(?i)\bAPI\b', r'(?i)\bsdk\b',
    r'(?i)\bvector\b', r'(?i)\bdiffusion\b',
    r'(?i)\bscale\b.*\b(AI|model|infra)',
    r'(?i)\bARC[-\s]?AGI', r'(?i)\bbenchmark\b',
    r'(?i)\breinforcement learning\b', r'(?i)\bRLHF\b',
    r'(?i)\bmultimodal\b', r'(?i)\bvision model\b',
    r'(?i)\bcontext window\b', r'(?i)\breasoning\b',
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
