# -*- coding: utf-8 -*-
import json
import os
import sys
import time
import subprocess
import socket
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect

# 确保在 frontend 目录下运行时的路径统一
CURRENT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = CURRENT_DIR.parent
ARTIFACTS_DIR = FRONTEND_DIR / "test-artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

PORT = int(os.environ.get("PORT", 8188))
BASE_URL = f"http://127.0.0.1:{PORT}/index.html"
ORIGIN = f"http://127.0.0.1:{PORT}"


def get_query_parameter(url):
    return parse_qs(urlparse(url).query).get("query", [""])[0]


def wait_for_request_count(requests, expected_count, timeout_seconds=8):
    deadline = time.time() + timeout_seconds
    while len(requests) < expected_count and time.time() < deadline:
        time.sleep(0.1)
    assert len(requests) >= expected_count, (
        f"学术请求数量不足，期望至少 {expected_count}，实际 {len(requests)}: {requests}"
    )

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def start_static_server_if_needed():
    if is_port_in_use(PORT):
        print(f"[playwright] static server already running on port {PORT}", flush=True)
        return None
    print(f"[playwright] starting static server on port {PORT}...", flush=True)
    proc = subprocess.Popen(
        ["node", "tests/static_server.mjs"],
        cwd=str(FRONTEND_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    for _ in range(30):
        if is_port_in_use(PORT):
            print(f"[playwright] static server started successfully.", flush=True)
            return proc
        time.sleep(0.2)
    raise RuntimeError(f"Failed to start static server on port {PORT}")


def main():
    server_proc = start_static_server_if_needed()
    console_errors = []
    stream_chat_requests = []
    academic_requests = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            user = {
                "id": 101,
                "username": "student_tester",
                "real_name": "学生测试员",
                "role": "student",
                "avatar_url": ""
            }
            installed_plugins = ["plugin_openalex", "plugin_arxiv", "plugin_crossref", "plugin_europepmc"]

            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                storage_state={
                    "cookies": [],
                    "origins": [
                        {
                            "origin": ORIGIN,
                            "localStorage": [
                                {"name": "isLoggedIn", "value": "true"},
                                {"name": "currentRole", "value": "student"},
                                {"name": "currentView", "value": "workspace"},
                                {"name": "isTeacherLogin", "value": "false"},
                                {"name": "currentUser", "value": json.dumps(user, ensure_ascii=False)},
                                {"name": "token", "value": "test-mock-token-abc"},
                                {"name": "installed_plugins:student_tester", "value": json.dumps(installed_plugins)},
                                {"name": "installed_plugins:guest", "value": json.dumps(installed_plugins)},

                            ],
                        }
                    ],
                },
                accept_downloads=True
            )
            page = context.new_page()

            # 错误捕获
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: print(f"[playwright pageerror] {err}", flush=True))
            
            # 网络监控
            def track_request(req):
                if "/api/chat/stream" in req.url:
                    stream_chat_requests.append(req.url)
                if "europepmc.org/articles/PMC" in req.url:
                    return
                request_path = urlparse(req.url).path
                if (request_path.startswith("/api/academic/") and request_path.endswith("/search")) \
                        or "/europepmc/webservices/rest/search" in request_path:
                    academic_requests.append(req.url)
            page.on("request", track_request)

            # Fixture 数据
            openalex_fixture = {
                "source": "openalex",
                "cached": False,
                "items": [
                    {
                        "id": "https://openalex.org/W2741809807",
                        "title": "Attention Is All You Need",
                        "publication_year": 2017,
                        "type": "preprint",
                        "primary_location": {
                            "landing_page_url": "https://arxiv.org/abs/1706.03762",
                            "pdf_url": "https://arxiv.org/pdf/1706.03762.pdf",
                            "is_oa": True,
                            "source": {"display_name": "arXiv"}
                        },
                        "authorships": [
                            {"author": {"display_name": "Ashish Vaswani"}},
                            {"author": {"display_name": "Noam Shazeer"}}
                        ],
                        "cited_by_count": 125000,
                        "abstract_inverted_index": {
                            "The": [0], "dominant": [1], "sequence": [2], "transduction": [3],
                            "models": [4], "are": [5], "based": [6], "on": [7], "complex": [8],
                            "recurrent": [9], "or": [10], "convolutional": [11], "neural": [12], "networks": [13]
                        }
                    }
                ]
            }

            arxiv_fixture = {
                "source": "arxiv",
                "cached": False,
                "items": [
                    {
                        "sourceId": "1706.03762",
                        "title": "Attention Is All You Need",
                        "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
                        "year": 2017,
                        "venue": "arXiv",
                        "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...",
                        "doi": "10.48550/arxiv.1706.03762",
                        "arxivId": "1706.03762",
                        "officialUrl": "https://arxiv.org/abs/1706.03762",
                        "openAccessUrl": "https://arxiv.org/pdf/1706.03762",
                        "isOpenAccess": True
                    }
                ]
            }

            crossref_fixture = {
                "source": "crossref",
                "cached": False,
                "items": [
                    {
                        "DOI": "10.5555/3295222.3295349",
                        "title": ["Attention is all you need"],
                        "author": [{"given": "Ashish", "family": "Vaswani"}],
                        "created": {"date-parts": [[2017, 12, 4]]},
                        "type": "proceedings-article",
                        "container-title": ["NIPS'17: Proceedings of the 31st International Conference on Neural Information Processing Systems"],
                        "URL": "https://dl.acm.org/doi/10.5555/3295222.3295349",
                        "is-referenced-by-count": 98000
                    }
                ]
            }

            europe_pmc_fixture = {
                "resultList": {
                    "result": [
                        {
                            "id": "31234567",
                            "pmid": "31234567",
                            "title": "Attention mechanisms and transformer networks in biological sequence analysis",
                            "authorString": "Vaswani A, Shazeer N",
                            "pubYear": "2018",
                            "journalTitle": "Bioinformatics",
                            "doi": "10.1093/bioinformatics/btz001",
                            "fullTextUrlList": {
                                "fullTextUrl": [
                                    {"url": "https://europepmc.org/articles/PMC31234567", "documentStyle": "html", "availabilityCode": "OA"}
                                ]
                            }
                        }
                    ]
                }
            }

            # 设置路由拦截
            arxiv_delayed = {"value": True}
            
            def handle_openalex(route):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(openalex_fixture))
            
            def handle_arxiv(route):
                if arxiv_delayed["value"]:
                    # 模拟延时 800ms
                    time.sleep(0.8)
                route.fulfill(status=200, content_type="application/json", body=json.dumps(arxiv_fixture))

            def handle_crossref(route):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(crossref_fixture))

            def handle_europepmc(route):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(europe_pmc_fixture))

            page.route("**/academic/openalex/search*", handle_openalex)
            page.route("**/academic/arxiv/search*", handle_arxiv)
            page.route("**/academic/crossref/search*", handle_crossref)
            page.route(re.compile(r".*europepmc.*search.*"), handle_europepmc)

            # 屏蔽与学术搜索无关的后台轮询接口，避免在无后端时产生 401 控制台噪音
            def mock_general_success(route):
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"code": 200, "data": {}}))

            page.route("**/api/analytics/**", mock_general_success)
            page.route("**/api/profile/**", mock_general_success)
            page.route("**/api/dashboard/**", mock_general_success)
            page.route("**/api/user/**", mock_general_success)


            chat_history_batch_requests = []
            def handle_chat_history_batch(route):
                post_data = route.request.post_data_json
                chat_history_batch_requests.append(post_data)
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "status": "success",
                        "message": "历史工作记录已保存",
                        "data": [
                            {"id": 8801, "role": "user", "agent_mode": "paper"},
                            {"id": 8802, "role": "assistant", "agent_mode": "paper"}
                        ]
                    })
                )

            page.route("**/api/chat/history/batch*", handle_chat_history_batch)
            page.route("**/api/chat/history*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"status": "success", "data": []})))

            print("[playwright] navigating to workspace...")
            page.goto(BASE_URL, wait_until="networkidle")
            page.screenshot(path=str(ARTIFACTS_DIR / "debug-init.png"))
            print(f"[playwright] current url: {page.url}")
            print(f"[playwright] console errors: {console_errors}")

            # 1. 切换到论文查询模式
            paper_mode_btn = page.locator("#btn-switch-mode-paper").first
            expect(paper_mode_btn).to_be_visible(timeout=8000)
            paper_mode_btn.click()
            print("[playwright] switched to paper search mode.")

            # 2. 输入查询并发送
            input_textarea = page.locator("textarea").first
            expect(input_textarea).to_be_visible()
            input_textarea.fill("Attention Is All You Need")

            send_button = page.locator("#workspace-send-btn").first
            expect(send_button).to_be_enabled()
            send_button.click()
            print("[playwright] clicked search send button.")

            # 3. 验证网络无 /api/chat/stream
            time.sleep(0.3)
            assert len(stream_chat_requests) == 0, f"发现不应有的 /api/chat/stream 请求: {stream_chat_requests}"

            # 4. 验证来源增量状态栏显示
            # 在 arxiv 延时期间或之后，应该能看到 OpenAlex / arXiv 来源状态
            expect(page.locator("text=多来源可核验检索").first).to_be_visible(timeout=6000)
            expect(page.locator("text=OpenAlex").first).to_be_visible()
            expect(page.locator("text=arXiv").first).to_be_visible()

            # 等待所有检索完成
            expect(page.locator("text=去重后").first).to_be_visible(timeout=8000)
            print("[playwright] multi-source results merged successfully.")

            # 验证历史记录已向后端同步
            time.sleep(0.5)
            assert len(chat_history_batch_requests) >= 1, "论文检索完成后必须调用 /api/chat/history/batch 保存工作记录"
            paper_history_req = chat_history_batch_requests[0]
            assert paper_history_req.get("agent_mode") == "paper", f"历史工作记录 agent_mode 错误: {paper_history_req}"
            assert any(m.get("content") == "Attention Is All You Need" for m in paper_history_req.get("messages", [])), "历史记录必须包含用户检索 query"
            print("[playwright] paper history DB sync request verified.", flush=True)

            # 验证左侧任务列表记录了论文查询工作
            paper_proj_node = page.locator('[data-project-id="proj-paper"]').first
            expect(paper_proj_node).to_be_visible()
            # 验证任务列表包含子任务记录
            paper_task_item = page.locator('[data-project-id="proj-paper"] [data-task-id]').first
            expect(paper_task_item).to_be_visible(timeout=5000)
            expect(paper_task_item).to_contain_text("Attention Is All You Nee")
            print("[playwright] left sidebar task tree records paper query verified.", flush=True)

            # 点击发送必须把输入文本原样作为 query，不能传入 [object PointerEvent]
            wait_for_request_count(academic_requests, len(installed_plugins))
            click_requests = academic_requests[:len(installed_plugins)]
            assert all(get_query_parameter(url) == "Attention Is All You Need" for url in click_requests), (
                f"点击发送的真实 query 参数错误: {click_requests}"
            )

            # 5. 验证论文卡片展示与安全外链
            paper_card = page.locator("h4:has-text('Attention Is All You Need')").first
            expect(paper_card).to_be_visible(timeout=5000)

            # 验证外链属性: target="_blank", rel="noopener noreferrer", safe http(s)
            official_link = page.locator("a:has-text('访问官方论文页面')").first
            expect(official_link).to_be_visible()
            assert official_link.get_attribute("target") == "_blank"
            assert "noopener" in official_link.get_attribute("rel")
            assert "noreferrer" in official_link.get_attribute("rel")
            assert official_link.get_attribute("href").startswith("http")

            oa_link = page.locator("a:has-text('打开开放全文')").first
            expect(oa_link).to_be_visible()
            assert oa_link.get_attribute("target") == "_blank"
            assert "noopener" in oa_link.get_attribute("rel")
            assert "noreferrer" in oa_link.get_attribute("rel")
            assert oa_link.get_attribute("href").startswith("http")

            # 保存搜索结果截图
            page.screenshot(path=str(ARTIFACTS_DIR / "paper-search-results.png"))
            print(f"[playwright] saved screenshot: paper-search-results.png")

            # 6. 打开详情弹窗并验证元数据
            detail_btn = page.locator("button:has-text('查看详情')").first
            expect(detail_btn).to_be_visible()
            # 结果区为内部滚动容器，headless Chromium 有时误判按钮在页面 viewport 外。
            detail_btn.evaluate("element => element.click()")

            # 弹窗内元素验证
            expect(page.locator("h3:has-text('Attention Is All You Need')").first).to_be_visible(timeout=5000)
            expect(page.locator("text=作者团队").first).to_be_visible()
            expect(page.locator("text=学术标识符").first).to_be_visible()
            expect(page.locator("text=引用统计与来源").first).to_be_visible()
            expect(page.locator("text=论文摘要").first).to_be_visible()

            # 保存详情截图
            page.screenshot(path=str(ARTIFACTS_DIR / "paper-search-detail.png"))
            print(f"[playwright] saved screenshot: paper-search-detail.png")

            # 7. 验证下载 .bib 引用
            with page.expect_download(timeout=5000) as download_info:
                page.locator("button:has-text('下载 .bib')").first.click()
            download = download_info.value
            assert download.suggested_filename.endswith(".bib"), f"下载文件名不以 .bib 结尾: {download.suggested_filename}"
            print(f"[playwright] downloaded citation file: {download.suggested_filename}")

            # 8. Esc 键盘关闭详情弹窗
            page.keyboard.press("Escape")
            time.sleep(0.3)
            expect(page.locator("h3:has-text('Attention Is All You Need')")).not_to_be_visible()
            print("[playwright] closed detail modal with Escape.")

            # 回车发送使用不同查询词，确保 KeyboardEvent 同样不会污染 query
            enter_query = "Graph Neural Networks"
            request_count_before_enter = len(academic_requests)
            input_textarea = page.locator("textarea").first
            input_textarea.fill(enter_query)
            input_textarea.press("Enter")
            wait_for_request_count(academic_requests, request_count_before_enter + len(installed_plugins))
            enter_requests = academic_requests[request_count_before_enter:request_count_before_enter + len(installed_plugins)]
            assert all(get_query_parameter(url) == enter_query for url in enter_requests), (
                f"回车发送的真实 query 参数错误: {enter_requests}"
            )
            assert len(stream_chat_requests) == 0, "论文模式点击与回车均不得调用聊天流"
            print("[playwright] click and Enter query parameters verified.")

            # 9. 测试空插件来源搜索时的安全拦截与添加引导
            print("[playwright] testing empty plugin sources behavior...", flush=True)
            page.evaluate("""() => {
                localStorage.setItem('installed_plugins:student_tester', '[]');
                localStorage.setItem('installed_plugins:guest', '[]');
                if (window.__app__) {
                    window.__app__.installedPluginIds = [];
                }
            }""")
            page.reload(wait_until="networkidle")
            
            paper_mode_btn = page.locator("#btn-switch-mode-paper").first
            paper_mode_btn.click()

            academic_requests_before = len(academic_requests)
            input_textarea = page.locator("textarea").first
            input_textarea.fill("Deep Learning Without Plugins")
            page.locator("#workspace-send-btn").first.click()

            time.sleep(0.5)
            # 断言没有发起学术网络请求
            assert len(academic_requests) == academic_requests_before, "卸载来源后不应发起学术 API 请求"
            # 断言显示去添加来源引导
            expect(page.locator("text=去添加来源").first).to_be_visible(timeout=5000)
            print("[playwright] empty sources guard verified.", flush=True)

            # 10. 快速连续重查与旧请求取消测试
            print("[playwright] testing fast resubmit & old query abort...", flush=True)
            page.evaluate("""() => {
                const ids = ['plugin_openalex', 'plugin_arxiv'];
                localStorage.setItem('installed_plugins:student_tester', JSON.stringify(ids));
                localStorage.setItem('installed_plugins:guest', JSON.stringify(ids));
                if (window.__app__) {
                    window.__app__.installedPluginIds = ids;
                }
            }""")

            page.reload(wait_until="networkidle")
            paper_mode_btn = page.locator("#btn-switch-mode-paper").first
            paper_mode_btn.click()

            arxiv_delayed["value"] = False
            # 路由针对不同 query 做区分
            def handle_custom_openalex(route):
                req_url = route.request.url
                if "transformer" in req_url.lower():
                    time.sleep(1.2)
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({
                        "source": "openalex", "items": [{"id": "W1", "title": "Old Transformer Paper", "publication_year": 2018}]
                    }))
                else:
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({
                        "source": "openalex", "items": [{"id": "W2", "title": "New Graph Neural Network Paper", "publication_year": 2021}]
                    }))

            page.unroute("**/academic/openalex/search*")
            page.route("**/academic/openalex/search*", handle_custom_openalex)

            # 快速连续触发两次检索（通过 executePaperSearch 或界面，验证 abort controller 取消旧请求）
            page.evaluate("() => window.__app__.executePaperSearch('transformer')")
            time.sleep(0.1)
            page.evaluate("() => window.__app__.executePaperSearch('graph neural network')")

            # 等待结果稳定
            expect(page.locator("text=New Graph Neural Network Paper").first).to_be_visible(timeout=8000)
            # 等待确认第一轮完成被丢弃，没有覆盖第二轮
            time.sleep(1.5)
            expect(page.locator("text=New Graph Neural Network Paper").first).to_be_visible()
            assert not page.locator("text=Old Transformer Paper").is_visible(), "旧查询响应不应覆盖新查询结果"
            print("[playwright] fast resubmit cancellation verified.", flush=True)

            # 8. 验证检索后返回对话框按钮与交互链路
            header_return_btn = page.locator("#header-return-to-chat-btn").first
            expect(header_return_btn).to_be_visible()
            status_return_btn = page.locator("#status-return-to-chat-btn").first
            expect(status_return_btn).to_be_visible()
            float_return_btn = page.locator("#float-return-to-chat-btn").first
            expect(float_return_btn).to_be_visible()
            bottom_return_btn = page.locator("#bottom-return-to-chat-btn").first
            expect(bottom_return_btn).to_be_visible()

            # 点击顶部 Header 的返回对话框按钮
            header_return_btn.click()
            time.sleep(0.3)
            # 验证模式成功切回 AI 对话
            expect(page.locator("text=AI 对话 · 自由问答助手").first).to_be_visible()
            print("[playwright] return to chat button via header verified.", flush=True)

            # 重新切回论文模式，测试引入对话按钮联动返回对话框
            paper_mode_btn = page.locator("#btn-switch-mode-paper").first
            paper_mode_btn.click()
            time.sleep(0.3)
            expect(page.locator("text=New Graph Neural Network Paper").first).to_be_visible()
            insert_chat_btn = page.locator("button:has-text('引入对话')").first
            insert_chat_btn.click()
            time.sleep(0.3)
            # 验证引入对话后自动切回 AI 对话模式且输入框含有参考论文内容
            expect(page.locator("text=AI 对话 · 自由问答助手").first).to_be_visible()
            textarea_val = page.locator("textarea").first.input_value()
            assert "参考论文" in textarea_val, f"引入对话后输入框内容不符合预期: {textarea_val}"
            print("[playwright] insert paper to chat with auto return verified.", flush=True)

            browser.close()


        # 检查控制台错误
        fatal_errors = [
            e for e in console_errors
            if "favicon" not in e and "401" not in e and "Unauthorized" not in e and "API Request Error" not in e
        ]
        assert len(fatal_errors) == 0, f"控制台存在严重前端错误: {fatal_errors}"

        print("paper search browser checks passed", flush=True)
        sys.exit(0)


    finally:
        if server_proc:
            server_proc.terminate()
            server_proc.wait()

if __name__ == "__main__":
    main()
