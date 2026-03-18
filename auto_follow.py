"""
Auto-follow users whose tweets are classified as "quality" and we don't already follow.
Reads classified JSON from stdin (with `verdict` field).
Uses Playwright + logged-in Chrome (CDP at 18800) to follow each user.

Safety:
- Max 5 follows per run
- Random delay 3-8s between actions
- Gracefully skips if already following
"""
import asyncio
import json
import random
import sys
from playwright.async_api import async_playwright

MAX_FOLLOWS_PER_RUN = 5


async def follow_user(page, handle: str) -> bool:
    """Navigate to @handle profile and click Follow if not already following. Returns True if followed."""
    handle = handle.split("·", 1)[0].split()[0].strip().lstrip("@")
    try:
        await page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(3000)

        # Check if already following
        # "Following" button means we already follow; "Follow" means we don't
        following_btn = page.locator('[data-testid="placementTracking"] [aria-label^="Following"]').first
        if await following_btn.count() > 0:
            print(f"  Already following @{handle}", file=sys.stderr)
            return False

        # Find the Follow button
        follow_btn = page.locator('[data-testid="placementTracking"] [aria-label^="Follow @"]').first
        if await follow_btn.count() == 0:
            # Try alternative selector
            follow_btn = page.locator(f'[aria-label="Follow @{handle}"]').first
        if await follow_btn.count() == 0:
            print(f"  Follow button not found for @{handle}", file=sys.stderr)
            return False

        await follow_btn.click()
        await page.wait_for_timeout(1500)
        print(f"  Followed @{handle}", file=sys.stderr)
        return True

    except Exception as e:
        print(f"  Error following @{handle}: {e}", file=sys.stderr)
        return False


async def main():
    raw = sys.stdin.read()
    tweets = json.loads(raw)

    # Get unique handles from quality tweets
    quality_handles = []
    seen = set()
    for t in tweets:
        if t.get("verdict") == "quality":
            handle = t.get("handle", "")
            if handle and handle not in seen:
                seen.add(handle)
                quality_handles.append(handle)

    if not quality_handles:
        print("No quality tweets to follow.", file=sys.stderr)
        return

    to_follow = quality_handles[:MAX_FOLLOWS_PER_RUN]
    print(f"Quality tweet authors: {len(quality_handles)}, attempting to follow up to {len(to_follow)}", file=sys.stderr)

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:18800")
        context = browser.contexts[0]
        page = await context.new_page()

        followed = 0
        for handle in to_follow:
            if await follow_user(page, handle):
                followed += 1
            delay = random.uniform(3, 8)
            await page.wait_for_timeout(int(delay * 1000))

        await page.close()
        print(f"\nFollowed {followed} new users.", file=sys.stderr)


asyncio.run(main())
