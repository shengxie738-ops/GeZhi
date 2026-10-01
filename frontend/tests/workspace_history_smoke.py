import os
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


def history_payload(mode):
    if mode == "rag":
        return {
            "status": "success",
            "data": [
                {
                    "id": 101,
                    "role": "user",
                    "sender_id": None,
                    "content": "rag question",
                    "created_at": "2026-06-30 23:35:10",
                },
                {
                    "id": 102,
                    "role": "assistant",
                    "sender_id": "agent_researcher",
                    "content": "rag answer",
                    "created_at": "2026-06-30 23:35:25",
                },
                {
                    "id": 103,
                    "role": "user",
                    "sender_id": None,
                    "content": "second rag question",
                    "created_at": "2026-06-30 23:40:10",
                },
                {
                    "id": 104,
                    "role": "assistant",
                    "sender_id": "agent_researcher",
                    "content": "second rag answer",
                    "created_at": "2026-06-30 23:40:25",
                },
            ],
        }
    return {
        "status": "success",
        "data": [
            {
                "id": 201,
                "role": "user",
                "sender_id": None,
                "content": "tutor question",
                "created_at": "2026-06-30 23:34:10",
            },
            {
                "id": 202,
                "role": "assistant",
                "sender_id": "agent_tutor",
                "content": "tutor answer",
                "created_at": "2026-06-30 23:34:25",
            },
        ],
    }


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    page.route(
        "**/api/chat/history**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            json=history_payload(
                parse_qs(urlparse(route.request.url).query).get("agent_mode", ["tutor"])[0]
            ),
        ),
    )

    page.add_init_script(
        """
localStorage.setItem('isLoggedIn', 'true');
localStorage.setItem('currentRole', 'student');
localStorage.setItem('currentView', 'workspace');
localStorage.setItem('currentUser', JSON.stringify({ username: 'alice' }));
localStorage.removeItem('messages:alice:tutor');
localStorage.removeItem('messages:alice:rag');
"""
    )
    base_url = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8088")
    page.goto(f"{base_url}/index.html", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)

    # 进入知识库检索（RAG）模式：双栏布局，左侧为检索历史 + 新增对话
    page.locator("text=DataBot").click()
    expect(page.locator(".knowledge-search-shell")).to_be_visible(timeout=5000)
    expect(page.locator(".workspace-sidebar")).to_be_visible()
    expect(page.locator("text=检索历史")).to_be_visible()
    expect(page.locator("text=新增对话")).to_be_visible()
    expect(page.locator("text=rag question").first).to_be_visible(timeout=5000)
    expect(page.locator("text=second rag question").first).to_be_visible()

    # 默认展示最新对话
    expect(page.locator("text=second rag answer").first).to_be_visible()

    # 点击新增对话：对话区进入空白欢迎态
    page.locator("button", has_text="新增对话").click()
    expect(page.locator("text=开始一次有来源的知识检索")).to_be_visible(timeout=5000)

    # 点击较早的对话：进入历史回顾态，出现提示条，可回到最新
    page.locator('.workspace-conversation-item[title="rag question"]').click()
    expect(page.locator("text=正在查看历史对话")).to_be_visible(timeout=5000)
    expect(page.locator("text=rag answer").first).to_be_visible()
    page.locator("button", has_text="回到最新对话").click()
    expect(page.locator("text=正在查看历史对话")).not_to_be_visible()
    expect(page.locator("text=second rag answer").first).to_be_visible()

    # 返回模式选择并切换到引导式学习（tutor）：三栏布局，历史互相隔离
    page.locator("button[title]").first.click()
    page.locator("text=Alina").click()
    expect(page.locator(".visual-guide-panel")).to_be_visible(timeout=5000)
    expect(page.locator("text=对话历史")).to_be_visible()
    expect(page.locator("text=tutor question").first).to_be_visible(timeout=5000)
    expect(page.locator("text=rag question")).not_to_be_visible()

    assert not errors, "\\n".join(errors)
    browser.close()

print("workspace_history_smoke: all assertions passed")
