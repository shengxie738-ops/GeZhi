import json
import os
import sys
import time
import subprocess
import socket
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

# 确保在 frontend 目录下运行时的路径统一
CURRENT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = CURRENT_DIR.parent
ARTIFACTS_DIR = FRONTEND_DIR / "test-artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

PORT = int(os.environ.get("PORT", 8188))
BASE_URL = f"http://127.0.0.1:{PORT}/index.html"
ORIGIN = f"http://127.0.0.1:{PORT}"

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
            
            # 网络监控
            def track_request(req):
                if "/api/chat/stream" in req.url:
                    stream_chat_requests.append(req.url)
                if "academic" in req.url or "europepmc" in req.url:
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
            page.route("*europepmc*search*", handle_europepmc)

            # 屏蔽与学术搜索无关的后台轮询接口，避免在无后端时产生 401 控制台噪音
            def mock_general_success(route):
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"code": 200, "data": {}}))

            page.route("**/api/analytics/**", mock_general_success)
            page.route("**/api/profile/**", mock_general_success)
            page.route("**/api/dashboard/**", mock_general_success)
            page.route("**/api/user/**", mock_general_success)


            print("[playwright] navigating to workspace...")
            page.goto(BASE_URL, wait_until="networkidle")

            # 1. 切换到论文查询模式
            paper_mode_btn = page.locator("button:has-text('论文查询')").first
            expect(paper_mode_btn).to_be_visible(timeout=8000)
            paper_mode_btn.click()
            print("[playwright] switched to paper search mode.")

            # 2. 输入查询并发送
            input_textarea = page.locator("textarea").first
            expect(input_textarea).to_be_visible()
            input_textarea.fill("Attention Is All You Need")

            send_button = page.locator("button:has-text('发送')").first
            expect(send_button).to_be_enabled()
            send_button.click()
            print("[playwright] clicked search send button.")

            # 3. 验证网络无 /api/chat/stream
            time.sleep(0.3)
            assert len(stream_chat_requests) == 0, f"发现不应有的 /api/chat/stream 请求: {stream_chat_requests}"

            # 4. 验证来源增量状态栏显示
            # 在 arxiv 延时期间或之后，应该能看到 OpenAlex / arXiv 来源状态
            expect(page.locator("text=多来源真实检索").first).to_be_visible(timeout=6000)
            expect(page.locator("text=OpenAlex").first).to_be_visible()
            expect(page.locator("text=arXiv").first).to_be_visible()

            # 等待所有检索完成
            expect(page.locator("text=去重后").first).to_be_visible(timeout=8000)
            print("[playwright] multi-source results merged successfully.")

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
            detail_btn.click()

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
            
            paper_mode_btn = page.locator("button:has-text('论文查询')").first
            paper_mode_btn.click()

            academic_requests_before = len(academic_requests)
            input_textarea = page.locator("textarea").first
            input_textarea.fill("Deep Learning Without Plugins")
            page.locator("button:has-text('发送')").first.click()

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
            paper_mode_btn = page.locator("button:has-text('论文查询')").first
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
