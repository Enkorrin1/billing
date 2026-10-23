import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel='msedge', headless=True)
        ctx = await b.new_context(viewport={'width': 1366, 'height': 850})
        page = await ctx.new_page()

        await page.goto('http://127.0.0.1:8780/?login=1')
        await page.wait_for_timeout(1000)

        email = await page.query_selector('input[name="email"]')
        if email:
            await page.fill('input[name="email"]', 'admin@team.demo')
            await page.fill('input[name="password"]', 'TeamReview123!')
            await page.click('button.primary')
            await page.wait_for_timeout(1500)

        await page.click('[data-nav="tickets"]')
        await page.wait_for_selector('#ticket-list', timeout=10000)
        await page.wait_for_timeout(1000)

        await page.screenshot(path='output/screenshots/fixed_tickets_table.png')
        print('Screenshot saved: output/screenshots/fixed_tickets_table.png')
        await b.close()

asyncio.run(run())
