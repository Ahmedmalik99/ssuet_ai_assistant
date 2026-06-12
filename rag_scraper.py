#!/usr/bin/env python
"""
scraper_from_csv.py  (Playwright edition)
-----------------------------------------
Read a CSV file (one URL per line, or a column named 'url'), download each page,
strip scripts/styles/nav/footer, keep ALL clean text (no size cap),
and store each page as a JSON-Lines record in rag_data/ssuet_pages.jsonl.

Uses Playwright (headless Chrome) so JavaScript-rendered faculty pages
load fully before text is extracted.

Install once:
    pip install playwright beautifulsoup4 lxml
    playwright install chromium
"""

import csv
import time
import json
import hashlib
import os
import re
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── CONFIG ─────────────────────────────────────────────────────────────
CSV_PATH      = "ssuet_all_links.csv"
DATA_DIR      = "rag_data"
OUTPUT_FILE   = os.path.join(DATA_DIR, "ssuet_pages.jsonl")
REQUEST_DELAY = 1.5          # seconds between page loads (be polite)
PAGE_TIMEOUT  = 20_000       # ms to wait for page load
IDLE_TIMEOUT  = 8_000        # ms to wait for network idle after load
BASE_URL      = "https://www.ssuet.edu.pk"
USER_AGENT    = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
# ───────────────────────────────────────────────────────────────────────


def _load_robots() -> RobotFileParser:
    import requests
    rp = RobotFileParser()
    rp.set_url(urljoin(BASE_URL, "/robots.txt"))
    try:
        rp.read()
    except Exception as e:
        print(f"⚠️  robots.txt: {e}")
    return rp


def _allowed(url: str, rp: RobotFileParser) -> bool:
    try:
        return rp.can_fetch("*", url)
    except Exception:
        return True


def _clean_html(html: str) -> str:
    """Strip noise, return ALL readable text (no length cap)."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "canvas",
                     "header", "footer", "nav", "form", "iframe",
                     "path", "circle", "rect", "meta", "link"]):
        tag.decompose()

    # Faculty profile pages: target profile card
    profile = (
        soup.find("div", class_=re.compile(r"faculty.profile|faculty-detail|profile-card|team-member", re.I))
        or soup.find("div", id=re.compile(r"faculty|profile|member", re.I))
    )

    main = profile or soup.find("main") or soup.find("article")
    if not main:
        for cls in ("entry-content", "page-content", "content-area",
                    "content", "main", "container", "page", "site-content"):
            main = soup.find(class_=re.compile(cls, re.I))
            if main:
                break
    if not main:
        main = soup.body or soup

    raw = main.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in raw.splitlines()]
    return "\n".join(line for line in lines if line)


def _scrape_page(url: str, pw_page, rp: RobotFileParser) -> dict | None:
    if not _allowed(url, rp):
        print(f"🚫  robots.txt blocks: {url}")
        return None

    try:
        pw_page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        try:
            pw_page.wait_for_load_state("networkidle", timeout=IDLE_TIMEOUT)
        except PWTimeout:
            pass

        html = pw_page.content()
        title_el = pw_page.title()

    except PWTimeout:
        print(f"❌  Timeout: {url}")
        return None
    except Exception as e:
        print(f"❌  Error loading {url}: {e}")
        return None

    clean_text = _clean_html(html)

    if len(clean_text) < 50:
        print(f"⚠️   Very short ({len(clean_text)} chars) — skipping: {url}")
        return None

    return {
        "url":       url,
        "title":     title_el.strip() if title_el else "",
        "content":   clean_text,    # NO size cap — keep all content
        "timestamp": time.time(),
        "hash":      hashlib.md5(clean_text.encode("utf-8")).hexdigest(),
    }


def read_urls_from_csv(csv_path: str) -> list[str]:
    urls = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames and any("url" in h.lower() for h in reader.fieldnames):
            col = [h for h in reader.fieldnames if "url" in h.lower()][0]
            for row in reader:
                u = row[col].strip()
                if u:
                    urls.append(u)
        else:
            f.seek(0)
            for row in csv.reader(f):
                if row:
                    u = row[0].strip()
                    if u:
                        urls.append(u)
    seen, uniq = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def main():
    if not os.path.isfile(CSV_PATH):
        print(f"❌  CSV not found: {CSV_PATH}")
        return

    os.makedirs(DATA_DIR, exist_ok=True)

    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)
        print(f"🗑️   Cleared old {OUTPUT_FILE}")

    rp   = _load_robots()
    urls = read_urls_from_csv(CSV_PATH)
    print(f"🔎  {len(urls)} unique URLs loaded from {CSV_PATH}")

    batch, batch_size = [], 50

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800},
            java_script_enabled=True,
        )
        pw_page = context.new_page()

        for i, url in enumerate(urls, start=1):
            print(f"[{i}/{len(urls)}]  {url}")
            record = _scrape_page(url, pw_page, rp)

            if record:
                batch.append(record)
                print(f"   ✅  {len(record['content'])} chars  |  {record['title'][:60]}")
            else:
                print(f"   ⏭️   Skipped")

            time.sleep(REQUEST_DELAY)

            if len(batch) >= batch_size:
                with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                    for rec in batch:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(f"💾  Flushed {len(batch)} records → {OUTPUT_FILE}")
                batch.clear()

        browser.close()

    if batch:
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            for rec in batch:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"💾  Final {len(batch)} records → {OUTPUT_FILE}")

    count = sum(1 for _ in open(OUTPUT_FILE, encoding="utf-8"))
    print(f"\n✅  Done! {count} pages saved to {OUTPUT_FILE}")
    print("   Next steps:")
    print("   1. Delete rag_data/faiss_index.bin")
    print("   2. Delete rag_data/metadata.pkl")
    print("   3. Run: python rag_engine.py")


if __name__ == "__main__":
    main()