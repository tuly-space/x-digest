"""
X/Twitter For You Timeline Scraper
Connects to Chrome via CDP, scrolls the For You timeline, extracts tweets.
Outputs JSON to stdout.
"""
import asyncio
import json
import sys
from playwright.async_api import async_playwright

SCROLL_ROUNDS = 15  # ~80-120 tweets
SCROLL_PX = 1000
SCROLL_WAIT_MS = 2000

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:18800")
        context = browser.contexts[0]
        page = await context.new_page()

        try:
            await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)

            # Make sure we're on "For you" tab
            try:
                for_you_tab = page.locator('a[role="tab"]:has-text("For you")')
                if await for_you_tab.count() > 0:
                    await for_you_tab.click()
                    await page.wait_for_timeout(2000)
            except Exception:
                pass

            # Scroll and collect
            for _ in range(SCROLL_ROUNDS):
                await page.evaluate(f"window.scrollBy(0, {SCROLL_PX})")
                await page.wait_for_timeout(SCROLL_WAIT_MS)

            tweets = await page.evaluate("""
            () => {
                const articles = document.querySelectorAll('article[data-testid="tweet"]');
                const results = [];
                const seen = new Set();
                for (const article of articles) {
                    try {
                        const userEl = article.querySelector('[data-testid="User-Name"]');
                        const textEl = article.querySelector('[data-testid="tweetText"]');
                        const timeEl = article.querySelector('time');
                        const linkEl = article.querySelector('a[href*="/status/"]');
                        const replyEl = article.querySelector('[data-testid="reply"]');
                        const retweetEl = article.querySelector('[data-testid="retweet"]');
                        const likeEl = article.querySelector('[data-testid="like"]');

                        const link = linkEl ? linkEl.getAttribute('href') : '';
                        if (seen.has(link)) continue;
                        seen.add(link);

                        // Parse user info
                        const rawUser = userEl ? userEl.textContent.trim() : '';
                        // Try to extract display name and handle
                        const handleMatch = rawUser.match(/@(\\w+)/);
                        const handle = handleMatch ? handleMatch[1] : '';
                        const displayName = rawUser.split('@')[0].replace(/[·•].*/, '').trim();

                        results.push({
                            displayName,
                            handle,
                            text: textEl ? textEl.textContent.trim() : '',
                            time: timeEl ? timeEl.getAttribute('datetime') : '',
                            link: link ? 'https://x.com' + link : '',
                            replies: replyEl ? replyEl.textContent.trim() : '0',
                            retweets: retweetEl ? retweetEl.textContent.trim() : '0',
                            likes: likeEl ? likeEl.textContent.trim() : '0',
                        });
                    } catch(e) {}
                }
                return results;
            }
            """)

            print(json.dumps(tweets, ensure_ascii=False))
        finally:
            await page.close()

asyncio.run(main())
