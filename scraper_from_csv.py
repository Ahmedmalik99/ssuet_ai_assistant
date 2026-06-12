#!/usr/bin/env python
"""
scraper_from_csv.py
-------------------
Read a CSV file (one URL per line, or a column named 'url'), download each page,
strip scripts/styles/nav/footer, keep the first ~5 000 characters of clean text,
and store each page as a JSON‑Lines record in rag_data/ssuet_pages.jsonl.

The script is polite:
  * respects robots.txt,
  * uses a configurable REQUEST_DELAY (seconds) between HTTP calls,
  * identifies itself with a clear User‑Agent,
  * writes data in batches so an interruption does not lose everything.
"""

import csv
import time
import json
import hashlib
import os
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------
# USER‑CONFIGURATION
# ----------------------------------------------------------------------
CSV_PATH = "ssuet_all_links.csv"          # <-- put your CSV here
DATA_DIR = "rag_data"
OUTPUT_FILE = os.path.join(DATA_DIR, "ssuet_pages.jsonl")
REQUEST_DELAY = 2.0                       # seconds between requests
USER_AGENT = ("SSUET AI Assistant RAG Bot (educational purpose; "
              "contact: admin@ssuet.edu.pk)")
# ----------------------------------------------------------------------


def _init_session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update({"User-Agent": USER_AGENT})
    return sess


def _load_robots(base_url: str) -> RobotFileParser:
    rp = RobotFileParser()
    rp.set_url(urljoin(base_url, "/robots.txt"))
    try:
        rp.read()
    except Exception as e:
        print(f"⚠️  Could not read robots.txt for {base_url}: {e}")
    return rp


def _allowed(url: str, rp: RobotFileParser) -> bool:
    try:
        return rp.can_fetch("*", url)
    except Exception:
        return False


def _clean_html_to_text(html: str) -> str:
    """Strip noise tags and return readable plain‑text."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "canvas",
                     "header", "footer", "nav", "form", "iframe"]):
        tag.decompose()
    # Try to locate a main content area
    main = soup.find("main") or soup.find("article")
    if not main:
        for cls in ("content", "main", "container", "page", "site-content"):
            main = soup.find("div", class_=cls)
            if main:
                break
    if not main:
        main = soup.body or soup
    text = main.get_text(separator=" ", strip=True)
    # Collapse whitespace / blank lines
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    return "\n".join(chunk for chunk in chunks if chunk)


def _scrape_one(url: str, sess: requests.Session, rp: RobotFileParser) -> dict | None:
    if not _allowed(url, rp):
        print(f"🚫 Skipping {url} (disallowed by robots.txt)")
        return None
    try:
        resp = sess.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"❌ Error fetching {url}: {e}")
        return None

    # Only process HTML
    ct = resp.headers.get("Content-Type", "").lower()
    if "text/html" not in ct:
        print(f"⏭️  Skipping non‑HTML ({ct}): {url}")
        return None

    clean_text = _clean_html_to_text(resp.text)
    if len(clean_text) < 50:
        print(f"⚠️  Very short content from {url} – skipping")
        return None

    record = {
        "url": url,
        "title": "",
        "content": clean_text[:5000],          # keep size manageable
        "timestamp": time.time(),
        "hash": hashlib.md5(clean_text.encode("utf-8")).hexdigest(),
    }
    # Try to capture a title
    try:
        soup_title = BeautifulSoup(resp.text, "lxml").find("title")
        if soup_title and soup_title.string:
            record["title"] = soup_title.string.strip()
    except Exception:
        pass
    return record


def read_urls_from_csv(csv_path: str) -> list[str]:
    """Accepts either a single‑column CSV (no header) or a CSV with a header
       that contains a column named 'url' (case‑insensitive)."""
    urls = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # If the file has no header, DictReader will treat the first row as header –
        # we fallback to reading raw rows.
        if reader.fieldnames and any("url" in h.lower() for h in reader.fieldnames):
            url_col = [h for h in reader.fieldnames if "url" in h.lower()][0]
            for row in reader:
                u = row[url_col].strip()
                if u:
                    urls.append(u)
        else:
            # No recognizable header – assume first column holds the URL
            f.seek(0)
            for row in csv.reader(f):
                if row:
                    u = row[0].strip()
                    if u:
                        urls.append(u)
    # Deduplicate while preserving order
    seen = set()
    uniq = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def main():
    if not os.path.isfile(CSV_PATH):
        print(f"❌ CSV file not found: {CSV_PATH}")
        return

    base_url = "https://www.ssuet.edu.pk"
    rp = _load_robots(base_url)
    sess = _init_session()
    os.makedirs(DATA_DIR, exist_ok=True)

    urls = read_urls_from_csv(CSV_PATH)
    print(f"🔎 Loaded {len(urls)} unique URLs from {CSV_PATH}")

    batch = []
    batch_size = 50
    for i, url in enumerate(urls, start=1):
        print(f"[{i}/{len(urls)}] Scraping: {url}")
        record = _scrape_one(url, sess, rp)
        if record:
            batch.append(record)
            print(f"   ✅ {len(record['content'])} chars saved")
        else:
            print(f"   ⏭️  Skipped")

        time.sleep(REQUEST_DELAY)

        if len(batch) >= batch_size:
            with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                for rec in batch:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"💾 Flushed {len(batch)} records → {OUTPUT_FILE}")
            batch.clear()

    # Write any remaining records
    if batch:
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            for rec in batch:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"💾 Final {len(batch)} records → {OUTPUT_FILE}")

    print("\n✅ Scraping complete.")
    print(f"   Data saved to {OUTPUT_FILE}")
    print("   Next step: run `python rag_engine.py` to build the FAISS index.")


if __name__ == "__main__":
    main()
