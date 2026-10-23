import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel='msedge', headless=True)

        # 1. Staff View
        ctx1 = await b.new_context(viewport={'width': 1366, 'height': 850})
        page1 = await ctx1.new_page()
        await page1.goto('http://127.0.0.1:8780/?login=1')
        await page1.wait_for_timeout(1000)
        email = await page1.query_selector('input[name="email"]')
        if email:
            await page1.fill('input[name="email"]', 'admin@team.demo')
            await page1.fill('input[name="password"]', 'TeamReview123!')
            await page1.click('button.primary')
            await page1.wait_for_timeout(1500)
        await page1.click('[data-nav="tickets"]')
        await page1.wait_for_selector('#ticket-list', timeout=10000)
        await page1.wait_for_timeout(500)
        await page1.screenshot(path='output/screenshots/staff_tickets_view.png')
        print('Saved output/screenshots/staff_tickets_view.png')
        await ctx1.close()

        # 2. Customer View
        ctx2 = await b.new_context(viewport={'width': 1366, 'height': 850})
        page2 = await ctx2.new_page()
        await page2.goto('http://127.0.0.1:8780/?login=1')
        await page2.wait_for_timeout(1000)
        email = await page2.query_selector('input[name="email"]')
        if email:
            await page2.fill('input[name="email"]', 'client@team.demo')
            await page2.fill('input[name="password"]', 'TeamReview123!')
            await page2.click('button.primary')
            await page2.wait_for_timeout(1500)
        await page2.click('[data-nav="tickets"]')
        await page2.wait_for_selector('#ticket-list', timeout=10000)
        await page2.wait_for_timeout(500)
        await page2.screenshot(path='output/screenshots/customer_tickets_view.png')
        print('Saved output/screenshots/customer_tickets_view.png')
        await ctx2.close()

        await b.close()

asyncio.run(run())
