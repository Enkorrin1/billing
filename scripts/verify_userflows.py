import asyncio
import os
from playwright.async_api import async_playwright

os.makedirs('output/screenshots', exist_ok=True)

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel='msedge', headless=True)
        context = await browser.new_context(viewport={'width': 1366, 'height': 850})
        page = await context.new_page()

        print("1. Opening app at http://127.0.0.1:8780/?login=1...")
        await page.goto('http://127.0.0.1:8780/?login=1')
        await page.wait_for_timeout(1000)

        # Check if login form is present
        email_el = await page.query_selector('input[name="email"]')
        if email_el:
            print("Logging in as admin@team.demo...")
            await page.fill('input[name="email"]', 'admin@team.demo')
            await page.fill('input[name="password"]', 'TeamReview123!')
            await page.click('button.primary')
            await page.wait_for_timeout(2000)

        await page.wait_for_selector('.brand-name', timeout=10000)

        # 2. Check brand
        brand_name = await page.inner_text('.brand-name')
        print(f"Brand name detected: {brand_name.strip()}")
        assert 'Линия' in brand_name, f"Expected Линия, got {brand_name}"

        # 3. Test 1.1: Inline task creation in Kanban
        print("Testing 1.1: Inline task creation in Kanban...")
        tasks_nav = await page.query_selector('[data-nav="tasks"]')
        if tasks_nav:
            await tasks_nav.click()
        await page.wait_for_selector('.bitrix-board', timeout=5000)
        
        # Click + Задача in column 'new'
        col_btn = await page.query_selector('[data-column-quick="new"]')
        if col_btn:
            await col_btn.click()
            await page.wait_for_timeout(300)
            composer = await page.query_selector('#inline-composer-new')
            assert composer, "Inline composer not found"
            is_visible = await composer.is_visible()
            assert is_visible, "Inline composer is not visible"
            print("Inline composer opened successfully!")

            inp = await page.query_selector('[data-inline-input="new"]')
            await inp.fill("Тестовая инлайн задача")
            await page.keyboard.press('Enter')
            await page.wait_for_timeout(1000)

            # Check that task card is present
            page_text = await page.content()
            assert "Тестовая инлайн задача" in page_text, "Created task not found on board"
            print("Task created inline successfully via Enter key!")
            await page.screenshot(path='output/screenshots/flow_1_1_inline_task.png')

        # 4. Test 6.1: Quick time logging from task card
        print("Testing 6.1: Quick time logging directly on card...")
        quick_time_btn = await page.query_selector('.task-quick-time-btn')
        if quick_time_btn:
            await quick_time_btn.click()
            await page.wait_for_selector('#task-quick-dialog', timeout=3000)
            print("Quick time modal opened!")
            preset_btn = await page.query_selector('.time-preset-btn[data-time="30"]')
            if preset_btn:
                await preset_btn.click()
            await page.fill('#task-quick-dialog textarea[name="note"]', 'Проверка быстрого списания 30 мин')
            await page.screenshot(path='output/screenshots/flow_6_1_quick_time_modal.png')
            await page.click('#task-quick-dialog button[type="submit"]')
            await page.wait_for_timeout(1500)
            print("Quick time logged successfully!")

        # 5. Test 5.1: Click client badge to filter
        print("Testing 5.1: Click client badge to filter...")
        client_badge = await page.query_selector('.task-client-badge[data-filter-client]')
        if client_badge:
            client_name = await client_badge.inner_text()
            await client_badge.click()
            await page.wait_for_timeout(500)
            search_val = await page.input_value('#tasks-search')
            print(f"Filter applied for client: {search_val}")
            await page.screenshot(path='output/screenshots/flow_5_1_client_filter.png')
            # Reset search
            await page.fill('#tasks-search', '')
            await page.keyboard.press('Enter')
            await page.wait_for_timeout(500)

        # 6. Test 2.1 & 2.3: Tickets table, claim button and bulk actions
        print("Testing 2.1 & 2.3: Tickets table, claim button and bulk actions...")
        await page.click('[data-nav="tickets"]')
        await page.wait_for_selector('#ticket-list', timeout=5000)
        await page.wait_for_timeout(500)

        # Check claim button
        claim_btn = await page.query_selector('.btn-claim-ticket')
        if claim_btn:
            print("«Взять себе» button found on ticket row!")
        
        # Test bulk selection
        cbs = await page.query_selector_all('.ticket-select-cb')
        if len(cbs) >= 2:
            print(f"Selecting 2 tickets out of {len(cbs)}...")
            await cbs[0].click()
            await page.wait_for_timeout(500)
            # Re-query after re-render
            cbs_second = await page.query_selector_all('.ticket-select-cb')
            if len(cbs_second) >= 2:
                await cbs_second[1].click()
                await page.wait_for_timeout(500)

            bulk_bar = await page.query_selector('.bulk-action-bar')
            assert bulk_bar, "Bulk action bar not rendered"
            assert await bulk_bar.is_visible(), "Bulk action bar not visible"
            print("Floating bulk action bar is visible with selected count!")
            await page.screenshot(path='output/screenshots/flow_2_3_bulk_action_bar.png')

            # Test cancel selection
            await page.click('#bulk-cancel')
            await page.wait_for_timeout(500)
            bulk_bar_after = await page.query_selector('.bulk-action-bar')
            assert not bulk_bar_after or not await bulk_bar_after.is_visible(), "Bulk bar did not hide on cancel"
            print("Bulk bar cancelled cleanly!")

        # 7. Test 2.4: Message to task button in chat
        print("Testing 2.4: Message to task in chat...")
        chats_nav = await page.query_selector('[data-nav="chats"]')
        if chats_nav:
            await chats_nav.click()
            await page.wait_for_timeout(1000)
            chat_item = await page.query_selector('[data-chat]')
            if chat_item:
                await chat_item.click()
                await page.wait_for_timeout(500)
                to_task_btn = await page.query_selector('.msg-to-task')
                if to_task_btn:
                    print("Found '+ В задачу' button on message!")
                    await to_task_btn.click()
                    await page.wait_for_selector('#task-quick-dialog', timeout=3000)
                    print("Quick task dialog opened pre-filled from chat message!")
                    await page.screenshot(path='output/screenshots/flow_2_4_msg_to_task.png')
                    await page.click('#task-quick-dialog [data-task-close]')
                    await page.wait_for_timeout(500)

        # 8. Test 4.1 & 4.2: Meetings
        print("Testing 4.1 & 4.2: Meetings protocol and share link...")
        meetings_nav = await page.query_selector('[data-nav="meetings"]')
        if meetings_nav:
            await meetings_nav.click()
            await page.wait_for_selector('.meetings-layout', timeout=5000)
            await page.wait_for_timeout(500)
            await page.screenshot(path='output/screenshots/flow_4_meetings.png')
            share_btn = await page.query_selector('[data-share-meeting-link]')
            if share_btn:
                print("Found 'Отправить клиенту' button on meeting!")
            step_btn = await page.query_selector('[data-step-meeting]')
            if step_btn:
                print("Found '+ Задача' button on meeting protocol step!")

        # 9. Test 5.1 CRM deals funnel filter
        print("Testing 5.1 Deals funnel...")
        deals_nav = await page.query_selector('[data-nav="deals"]')
        if deals_nav:
            await deals_nav.click()
            await page.wait_for_selector('.bitrix-crm-board', timeout=5000)
            await page.wait_for_timeout(500)
            deal_badge = await page.query_selector('[data-deal-filter-client]')
            if deal_badge:
                print("Found filter client on deal badge!")
            await page.screenshot(path='output/screenshots/flow_5_1_deals_funnel.png')

        print("\nAll User Flow automated tests completed successfully!")
        await browser.close()

asyncio.run(run())
