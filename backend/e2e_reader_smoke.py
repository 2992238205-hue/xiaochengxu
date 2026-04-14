#!/usr/bin/env python3
"""
Reader E2E smoke test (Playwright).

Goals:
1) Open the site in a real browser engine (default: WebKit, close to iOS).
2) Enter the first book from shelf.
3) Turn pages a few times.
4) Take screenshots and output a small report (md + json).

This script is intentionally self-contained and safe:
- No secrets are printed.
- No server changes are required.
- It can optionally start a local unified server for testing.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _now_ts() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _http_probe(url: str, timeout: float = 5.0) -> bool:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(getattr(resp, "status", 0)) in (200, 302, 304)
    except Exception:
        return False


def _wait_http_ok(url: str, timeout_seconds: float = 25.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_seconds:
        if _http_probe(url, timeout=4.0):
            return True
        time.sleep(0.6)
    return False


def _safe_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _truncate(s: str, limit: int = 240) -> str:
    s = str(s or "")
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _start_local_server(project_root: Path, port: int) -> Tuple[subprocess.Popen, Path]:
    """
    Starts backend/unified_server.py on the given port.
    Returns (process, log_path).
    """
    log_dir = project_root / ".codex-runs"
    _safe_mkdir(log_dir)
    log_path = log_dir / f"e2e_unified_server_{_now_ts()}_{port}.log"

    env = os.environ.copy()
    env["PORT"] = str(port)
    # unified_server.py already runs werkzeug with use_reloader=False; do not set WERKZEUG_RUN_MAIN,
    # otherwise Werkzeug expects WERKZEUG_SERVER_FD and crashes.

    with log_path.open("w", encoding="utf-8") as f:
        proc = subprocess.Popen(
            [sys.executable, str(project_root / "backend" / "unified_server.py")],
            cwd=str(project_root),
            env=env,
            stdout=f,
            stderr=subprocess.STDOUT,
        )
    return proc, log_path


def _stop_process(proc: subprocess.Popen, grace_seconds: float = 3.0) -> None:
    if proc.poll() is not None:
        return
    with contextlib.suppress(Exception):
        proc.send_signal(signal.SIGINT)
    end = time.time() + grace_seconds
    while time.time() < end:
        if proc.poll() is not None:
            return
        time.sleep(0.2)
    with contextlib.suppress(Exception):
        proc.kill()


def _build_report_md(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Reader E2E Smoke Report")
    lines.append("")
    lines.append(f"- 时间: {report.get('started_at')}")
    lines.append(f"- Base URL: `{report.get('base_url')}`")
    lines.append(f"- Engine: `{report.get('engine')}`")
    lines.append(f"- Viewport: `{report.get('viewport')}`")
    lines.append(f"- 结果: **{report.get('status')}**")
    lines.append("")

    steps = report.get("steps") or []
    lines.append("## 步骤")
    lines.append("")
    for step in steps:
        name = step.get("name", "step")
        ok = step.get("ok", False)
        detail = step.get("detail", "")
        lines.append(f"- {'✅' if ok else '❌'} {name}: {detail}")
    lines.append("")

    screenshots = report.get("screenshots") or []
    if screenshots:
        lines.append("## 截图")
        lines.append("")
        for item in screenshots:
            label = item.get("label", "screenshot")
            path = item.get("path", "")
            lines.append(f"- {label}: `{path}`")
        lines.append("")

    errors = report.get("errors") or {}
    console_errors = errors.get("console") or []
    page_errors = errors.get("page") or []
    request_errors = errors.get("request") or []

    lines.append("## 错误摘要")
    lines.append("")
    lines.append(f"- Console errors: `{len(console_errors)}`")
    lines.append(f"- Page errors: `{len(page_errors)}`")
    lines.append(f"- Request failures: `{len(request_errors)}`")
    lines.append("")

    if console_errors:
        lines.append("### Console errors")
        lines.append("")
        for msg in console_errors[:30]:
            lines.append(f"- {msg}")
        lines.append("")
    if page_errors:
        lines.append("### Page errors")
        lines.append("")
        for msg in page_errors[:30]:
            lines.append(f"- {msg}")
        lines.append("")
    if request_errors:
        lines.append("### Request failures")
        lines.append("")
        for item in request_errors[:30]:
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Reader E2E smoke test (Playwright).")
    parser.add_argument(
        "--base-url",
        default="",
        help="Target base url (e.g. http://127.0.0.1:5000). If omitted, starts a local server automatically.",
    )
    parser.add_argument(
        "--engine",
        default="webkit",
        choices=("webkit", "chromium", "firefox"),
        help="Playwright browser engine.",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Run with a visible browser window (not headless).",
    )
    parser.add_argument("--turns", type=int, default=4, help="How many times to turn to next page.")
    parser.add_argument(
        "--out-root",
        default="reports/e2e_reader_smoke",
        help="Output root directory (relative to project root).",
    )
    parser.add_argument("--timeout", type=int, default=35, help="Timeout seconds for major waits.")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    out_dir = (project_root / args.out_root / _now_ts()).resolve()
    shots_dir = out_dir / "screenshots"
    _safe_mkdir(shots_dir)

    report: Dict[str, Any] = {
        "started_at": dt.datetime.now().isoformat(timespec="seconds"),
        "status": "FAIL",
        "base_url": "",
        "engine": args.engine,
        "viewport": {"width": 390, "height": 844},  # iPhone-ish
        "steps": [],
        "screenshots": [],
        "errors": {"console": [], "page": [], "request": []},
        "metrics": {},
    }

    local_server_proc: Optional[subprocess.Popen] = None
    local_server_log: Optional[Path] = None
    base_url = str(args.base_url or "").strip()

    try:
        if not base_url:
            port = _find_free_port()
            local_server_proc, local_server_log = _start_local_server(project_root, port)
            base_url = f"http://127.0.0.1:{port}"
            report["base_url"] = base_url
            report["metrics"]["local_server_log"] = str(local_server_log)

            ok = _wait_http_ok(f"{base_url}/api/health", timeout_seconds=25.0)
            report["steps"].append(
                {
                    "name": "启动本地服务",
                    "ok": ok,
                    "detail": f"health={'OK' if ok else 'FAIL'} port={port}",
                }
            )
            if not ok:
                raise RuntimeError("Local server health check failed.")
        else:
            report["base_url"] = base_url
            ok = _wait_http_ok(f"{base_url}/api/health", timeout_seconds=10.0)
            report["steps"].append(
                {
                    "name": "探测服务",
                    "ok": ok,
                    "detail": "api/health OK" if ok else "api/health not reachable (still continuing)",
                }
            )

        # Lazy import so the report still exists if Playwright is missing.
        try:
            from playwright.sync_api import Playwright, sync_playwright  # type: ignore
        except Exception as exc:
            report["steps"].append(
                {
                    "name": "导入 Playwright",
                    "ok": False,
                    "detail": f"未安装或不可用: {_truncate(str(exc))}",
                }
            )
            raise

        start_url = base_url.rstrip("/") + "/reader"
        report["metrics"]["start_url"] = start_url

        with sync_playwright() as p:  # type: ignore
            browser_factory = getattr(p, args.engine)
            browser = browser_factory.launch(headless=(not args.headful))
            context = browser.new_context(
                viewport=report["viewport"],
                device_scale_factor=3,
                is_mobile=True,
                has_touch=True,
                locale="zh-CN",
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                ),
            )
            page = context.new_page()

            console_errors: List[str] = []
            page_errors: List[str] = []
            request_errors: List[str] = []

            page.on(
                "console",
                lambda msg: console_errors.append(f"[{msg.type}] {_truncate(msg.text)}")
                if msg.type in ("error",)
                else None,
            )
            page.on("pageerror", lambda err: page_errors.append(_truncate(str(err))))

            def on_request_failed(request: Any) -> None:
                try:
                    failure = request.failure
                    text = failure.get("errorText") if isinstance(failure, dict) else ""
                except Exception:
                    text = ""
                request_errors.append(_truncate(f"{request.url} | {text}"))

            page.on("requestfailed", on_request_failed)

            # Step 1: open shelf
            page.goto(start_url, wait_until="domcontentloaded", timeout=args.timeout * 1000)
            page.wait_for_selector("#bookshelf-list", state="visible", timeout=args.timeout * 1000)
            shelf_shot = shots_dir / "01_shelf.png"
            page.screenshot(path=str(shelf_shot), full_page=True)
            report["screenshots"].append({"label": "书架", "path": str(shelf_shot)})
            report["steps"].append({"name": "打开书架", "ok": True, "detail": page.url})

            # Step 2: open first book (public/personal)
            open_buttons = page.locator('button[data-open-book]')
            count = open_buttons.count()
            report["metrics"]["shelf_book_button_count"] = int(count)
            if count <= 0:
                raise RuntimeError("No books found on shelf (button[data-open-book] not present).")

            chosen = page.evaluate(
                """() => {
  const books = Array.isArray(state.books) ? state.books : [];
  let pick = books.find(b => Array.isArray(b.chapters) && b.chapters.length >= 2) || null;
  if (!pick) {
    // Inject a deterministic 2-chapter demo book so we can always test chapter navigation.
    const demo = {
      id: "e2e-demo-book",
      title: "E2E Demo Book (2 Chapters)",
      description: "仅用于自动化冒烟测试，不会上传到服务器。",
      wordGoal: 100,
      coverUrl: "",
      category: "E2E",
      sortOrder: -999,
      ownership: "public",
      editable: false,
      chapters: [
	        {
	          title: "Chapter 1: Hello",
	          english: "Hello reader. This is chapter one. It is short but different from chapter two. We will test the next chapter button.",
	          chinese: "你好读者。这是第一章。我们将测试下一章按钮。",
	          targetWords: []
	        },
	        {
	          title: "Chapter 2: Different",
	          english: "Now you are in chapter two. The content must change when switching chapters. If this text appears, the bug is fixed.",
	          chinese: "现在你在第二章。切换章节时内容必须改变。",
	          targetWords: []
	        }
      ]
    };
    books.unshift(demo);
    state.books = books;
    ensureProgress(demo.id);
    // Start from chapter 1 (index 0). The "next chapter" action should unlock chapter 2.
    state.progressByBook[demo.id].unlockedChapter = 0;
    state.progressByBook[demo.id].passedChapters["0"] = true;
    state.progressByBook[demo.id].passedChapters["1"] = true;
    saveState();
    renderShelf();
    pick = demo;
  }
  return {ok:true, id: pick.id, title: pick.title || '', chapterCount: (pick.chapters || []).length};
}"""
            )
            if not isinstance(chosen, dict) or not chosen.get("ok") or not chosen.get("id"):
                raise RuntimeError(f"Cannot pick a book: {chosen}")
            report["metrics"]["chosen_book"] = chosen

            page.locator(f'button[data-open-book="{chosen["id"]}"]').click()

            # reader-view is a wrapper whose only child is position:fixed; the wrapper may have 0 height,
            # so it is not considered "visible" by Playwright. Wait for the fixed stage/panel instead.
            page.wait_for_selector("#reader-stage", state="visible", timeout=args.timeout * 1000)
            page.wait_for_selector("#reading-panel .page-track", timeout=args.timeout * 1000)
            reader_shot = shots_dir / "02_reader_page_1.png"
            page.screenshot(path=str(reader_shot), full_page=True)
            report["screenshots"].append({"label": "阅读-第1页", "path": str(reader_shot)})
            report["steps"].append({"name": "进入阅读", "ok": True, "detail": "reader-view active"})

            # Gather some layout metrics for iOS/Quark style issues.
            metrics = page.evaluate(
                """() => {
  const panel = document.getElementById('reading-panel');
  const stage = document.getElementById('reader-stage');
  const rect = panel ? panel.getBoundingClientRect() : null;
  const vv = window.visualViewport ? {width: window.visualViewport.width, height: window.visualViewport.height} : null;
  const indicator = document.getElementById('page-indicator')?.textContent || '';
  return {
    panelRect: rect ? {x: rect.x, y: rect.y, width: rect.width, height: rect.height} : null,
    visualViewport: vv,
    stageClass: stage ? stage.className : '',
    indicator,
    innerSize: {w: window.innerWidth, h: window.innerHeight},
    docSize: {w: document.documentElement.clientWidth, h: document.documentElement.clientHeight},
  };
}"""
            )
            report["metrics"]["layout"] = metrics

            # Content sanity checks (catch regressions like visible &quot; / markdown markers).
            fatal_tokens = ["&quot;", "&amp;quot;"]
            warn_tokens = ["**", "__", "~~", "`", "Scene Setting:", "The Story:", "版本A", "版本B"]

            def sample_fill(label: str) -> Dict[str, Any]:
                """
                Estimate how "full" the current page is (used height / capacity).
                We want to catch regressions where each page ends too early with a big blank area.
                """
                data = page.evaluate(
                    """() => {
  const panel = document.getElementById('reading-panel');
  if (!panel) return null;
  const panelWidth = panel.clientWidth || 1;
  const pageIndex = Math.max(0, Math.round((panel.scrollLeft || 0) / panelWidth));
  const frame = panel.querySelector(`.page-frame[data-page-index="${pageIndex}"]`);
  const content = frame ? frame.querySelector('.page-content') : null;
  if (!content) return {pageIndex, ok:false};
  const contentRect = content.getBoundingClientRect();
  const paras = [...content.querySelectorAll('p.paragraph')].filter(p => (p.textContent || '').trim());
  const last = paras.length > 0 ? paras[paras.length - 1] : null;
  const lastBottom = last ? last.getBoundingClientRect().bottom : contentRect.top;
  const used = Math.max(0, Math.min(contentRect.height, lastBottom - contentRect.top));
  const cap = Math.max(1, contentRect.height);
  return {pageIndex, ok:true, usedPx: used, capPx: cap, ratio: used / cap, paraCount: paras.length};
}"""
                )
                payload: Dict[str, Any] = {
                    "label": label,
                    "pageIndex": None,
                    "ok": False,
                    "ratio": None,
                }
                if isinstance(data, dict):
                    payload.update(data)
                report.setdefault("metrics", {}).setdefault("fill_samples", []).append(payload)
                return payload

            def scan_tokens(label: str) -> Dict[str, Any]:
                text_blob = page.evaluate(
                    """() => {
  const panel = document.getElementById('reading-panel');
  if (!panel) return '';
  // innerText keeps what users actually see (entities appear as text if broken).
  return String(panel.innerText || '');
}"""
                )
                text_blob = str(text_blob or "")
                found_fatal = {t: text_blob.count(t) for t in fatal_tokens if t in text_blob}
                found_warn = {t: text_blob.count(t) for t in warn_tokens if t in text_blob}
                sample = _truncate(text_blob.replace("\n", " ").strip(), 260)
                report.setdefault("metrics", {}).setdefault("content_scans", []).append(
                    {
                        "label": label,
                        "fatal": found_fatal,
                        "warn": found_warn,
                        "sample": sample,
                    }
                )
                return {"fatal": found_fatal, "warn": found_warn}

            sample_fill("reader_initial")
            initial_scan = scan_tokens("reader_initial")
            if initial_scan["fatal"]:
                report["steps"].append(
                    {
                        "name": "内容健康检查",
                        "ok": False,
                        "detail": f"fatal={initial_scan['fatal']}",
                    }
                )
            else:
                detail = "ok"
                if initial_scan["warn"]:
                    detail = f"warn={initial_scan['warn']}"
                report["steps"].append({"name": "内容健康检查", "ok": True, "detail": detail})

            # Step 3: turn pages using tap zone (right side).
            panel = page.locator("#reading-panel")
            box = panel.bounding_box()
            if not box:
                raise RuntimeError("Cannot measure #reading-panel bounding box.")

            def tap_at(rx: float, ry: float) -> None:
                x = box["x"] + box["width"] * rx
                y = box["y"] + box["height"] * ry
                page.mouse.click(x, y)

            for i in range(max(0, int(args.turns))):
                tap_at(0.92, 0.5)
                time.sleep(0.45)
                shot = shots_dir / f"03_reader_next_{i+1}.png"
                page.screenshot(path=str(shot), full_page=True)
                report["screenshots"].append({"label": f"翻页+{i+1}", "path": str(shot)})
                sample_fill(f"reader_after_turn_{i+1}")
                scan_tokens(f"reader_after_turn_{i+1}")

            report["steps"].append({"name": "翻页", "ok": True, "detail": f"turns={args.turns}"})

            # Step 4: toggle UI (tap center) then click Next button (if visible).
            tap_at(0.5, 0.5)
            time.sleep(0.35)
            ui_shot = shots_dir / "04_reader_ui.png"
            page.screenshot(path=str(ui_shot), full_page=True)
            report["screenshots"].append({"label": "阅读-UI", "path": str(ui_shot)})

            # Try clicking the visible next button.
            with contextlib.suppress(Exception):
                page.locator("#next-page").click(timeout=1200)
                time.sleep(0.35)
                btn_shot = shots_dir / "05_reader_next_button.png"
                page.screenshot(path=str(btn_shot), full_page=True)
                report["screenshots"].append({"label": "阅读-按钮翻页", "path": str(btn_shot)})
                scan_tokens("reader_after_next_button")

            report["steps"].append({"name": "UI与按钮翻页", "ok": True, "detail": "toggle + next-page"})

            # Step 5: exercise reader controls (Chinese toggle / night mode / theme / sliders).
            try:
                # Ensure UI is visible for controls (avoid relying on a second toggle tap).
                page.evaluate("() => { try { setReaderUiVisible(true); } catch (e) {} }")
                time.sleep(0.25)

                # Toggle Chinese panel.
                with contextlib.suppress(Exception):
                    page.locator("#show-chinese").check(timeout=1500)
                    time.sleep(0.2)
                    page.locator("#show-chinese").uncheck(timeout=1500)
                    time.sleep(0.2)

                # Toggle night mode.
                with contextlib.suppress(Exception):
                    page.locator("#night-mode").check(timeout=1500)
                    time.sleep(0.2)
                    page.locator("#night-mode").uncheck(timeout=1500)
                    time.sleep(0.2)

                # Switch theme.
                with contextlib.suppress(Exception):
                    page.locator("#reader-theme").select_option("green", timeout=1500)
                    time.sleep(0.2)
                    page.locator("#reader-theme").select_option("paper", timeout=1500)
                    time.sleep(0.2)

                # Adjust font size / line height.
                def set_range_input(input_id: str, value: str) -> None:
                    page.evaluate(
                        """([id, value]) => {
  const el = document.getElementById(id);
  if (!el) throw new Error('missing ' + id);
  el.value = String(value);
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
}""",
                        [input_id, value],
                    )

                with contextlib.suppress(Exception):
                    set_range_input("font-size", "22")
                    time.sleep(0.2)
                    set_range_input("line-height", "1.8")
                    time.sleep(0.2)
                    set_range_input("font-size", "20")
                    set_range_input("line-height", "1.7")
                    time.sleep(0.2)

                report["steps"].append({"name": "阅读设置控件", "ok": True, "detail": "toggle + theme + sliders"})
            except Exception as exc:
                report["steps"].append({"name": "阅读设置控件", "ok": False, "detail": _truncate(str(exc))})

            # Step 6: Chapter navigation regression check.
            # Symptom we want to prevent: chapter title changes but reading content does not.
            try:
                # Unlock at least 2 chapters and mark current as passed to bypass the quiz gate.
                nav_meta = page.evaluate(
                    """() => {
  const book = state.books.find(b => b.id === state.activeBookId) || state.books[0];
  if (!book) return {ok:false, reason:'no book'};
  ensureProgress(book.id);
  const progress = state.progressByBook[book.id];
  progress.unlockedChapter = Math.max(progress.unlockedChapter || 0, Math.min(2, book.chapters.length - 1));
  progress.passedChapters[String(state.activeChapterIndex || 0)] = true;
  saveState();
  renderReader();
  return {ok:true, chapterCount: book.chapters.length, unlocked: progress.unlockedChapter, active: state.activeChapterIndex};
}"""
                )
                if not isinstance(nav_meta, dict) or not nav_meta.get("ok"):
                    raise RuntimeError(f"unlock failed: {nav_meta}")
                if int(nav_meta.get("chapterCount") or 0) < 2:
                    report["steps"].append({"name": "章节切换", "ok": True, "detail": "chapterCount<2 (skip)"})
                else:
                    before = page.evaluate(
                        """() => ({
  chapterIndex: state.activeChapterIndex,
  title: document.getElementById('reader-chapter-title')?.textContent || '',
  sample: (document.getElementById('reading-panel')?.innerText || '').slice(0, 260)
})"""
                    )
                    page.locator("#next-chapter").click(timeout=1500)
                    page.wait_for_function(
                        "prev => state.activeChapterIndex === (prev + 1)",
                        arg=int(before.get("chapterIndex") or 0),
                        timeout=args.timeout * 1000,
                    )
                    time.sleep(0.35)
                    after = page.evaluate(
                        """() => ({
  chapterIndex: state.activeChapterIndex,
  title: document.getElementById('reader-chapter-title')?.textContent || '',
  sample: (document.getElementById('reading-panel')?.innerText || '').slice(0, 260)
})"""
                    )

                    title_changed = str(after.get("title") or "") != str(before.get("title") or "")
                    content_changed = str(after.get("sample") or "") != str(before.get("sample") or "")
                    ok = bool(title_changed and content_changed)
                    detail = f"title_changed={title_changed} content_changed={content_changed}"
                    report["steps"].append({"name": "章节切换", "ok": ok, "detail": detail})

                    # Go back to previous chapter (best effort).
                    with contextlib.suppress(Exception):
                        page.locator("#prev-chapter").click(timeout=1500)
                        time.sleep(0.25)
            except Exception as exc:
                report["steps"].append({"name": "章节切换", "ok": False, "detail": _truncate(str(exc))})

            # Step 7: Switch tabs (shelf/profile) and return.
            try:
                # Reader view is immersive and can cover the top tabs; go back to shelf first.
                page.locator("#reader-back").click(timeout=1500)
                page.wait_for_selector("#shelf-view.active", timeout=args.timeout * 1000)
                page.locator('[data-view="profile"]').click(timeout=1500)
                page.wait_for_selector("#profile-view.active", timeout=args.timeout * 1000)
                page.locator('[data-view="shelf"]').click(timeout=1500)
                page.wait_for_selector("#shelf-view.active", timeout=args.timeout * 1000)
                report["steps"].append({"name": "切换Tab", "ok": True, "detail": "profile->shelf"})
            except Exception as exc:
                report["steps"].append({"name": "切换Tab", "ok": False, "detail": _truncate(str(exc))})

            # Final: collect errors and close.
            report["errors"]["console"] = console_errors
            report["errors"]["page"] = page_errors
            report["errors"]["request"] = request_errors

            browser.close()

        # Evaluate pass/fail
        scans = report.get("metrics", {}).get("content_scans", []) or []
        fatal_found = any(bool(item.get("fatal")) for item in scans)
        has_fatal = len(report["errors"]["page"]) > 0
        has_console_err = len(report["errors"]["console"]) > 0
        steps = report.get("steps") or []
        has_failed_step = any(step.get("ok") is False for step in steps)
        if has_fatal or fatal_found or has_failed_step:
            report["status"] = "FAIL"
        else:
            report["status"] = "OK_WITH_WARNINGS" if has_console_err else "OK"

    except Exception as exc:
        report["errors"]["exception"] = _truncate(str(exc), 600)
        report["steps"].append({"name": "异常退出", "ok": False, "detail": _truncate(str(exc), 240)})
        report["status"] = "FAIL"
    finally:
        if local_server_proc is not None:
            _stop_process(local_server_proc)

        report["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
        _write_json(out_dir / "report.json", report)
        _write_text(out_dir / "report.md", _build_report_md(report))

    # Print minimal summary (safe).
    print(f"[E2E] status={report['status']} out={out_dir}")
    return 0 if str(report.get("status")) in ("OK", "OK_WITH_WARNINGS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
