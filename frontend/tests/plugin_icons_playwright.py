import json
import sys

from playwright.sync_api import expect, sync_playwright


base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8188/index.html"
origin = base_url.split("/index.html", 1)[0]

user = {
    "id": 101,
    "username": "plugin_icon_tester",
    "real_name": "插件图标测试员",
    "role": "student",
    "avatar_url": "",
}

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        storage_state={
            "cookies": [],
            "origins": [
                {
                    "origin": origin,
                    "localStorage": [
                        {"name": "isLoggedIn", "value": "true"},
                        {"name": "currentRole", "value": "student"},
                        {"name": "currentView", "value": "workspace"},
                        {"name": "isTeacherLogin", "value": "false"},
                        {"name": "currentUser", "value": json.dumps(user, ensure_ascii=False)},
                    ],
                }
            ],
        },
    )
    page = context.new_page()
    page.goto(base_url, wait_until="networkidle", timeout=30000)

    page.locator("button:has-text('插件市场')").first.click()
    expect(page.get_by_text("格至插件市场")).to_be_visible(timeout=8000)

    card_icons = page.locator('[data-plugin-icon="market-card"]')
    expect(card_icons).to_have_count(9)
    for index in range(9):
        icon_state = card_icons.nth(index).evaluate(
            "icon => ({ complete: icon.complete, width: icon.naturalWidth, height: icon.naturalHeight })"
        )
        assert icon_state == {"complete": True, "width": 256, "height": 256}, icon_state

    page.locator("button:has-text('查看详情')").first.click()
    detail_icon = page.locator('[data-plugin-icon="plugin-detail"]')
    expect(detail_icon).to_be_visible()
    assert detail_icon.evaluate("icon => icon.complete && icon.naturalWidth === 256")

    page.locator("button:has-text('关闭')").last.click()
    page.locator("button:has-text('在线检索试用')").first.click()
    search_icon = page.locator('[data-plugin-icon="search-drawer"]')
    expect(search_icon).to_be_visible()
    assert search_icon.evaluate("icon => icon.complete && icon.naturalWidth === 256")

    browser.close()

print("plugin icon images rendered on marketplace cards, detail modal, and search drawer")
