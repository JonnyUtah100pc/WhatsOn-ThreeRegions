#!/usr/bin/env python3
# Scrape https://shropshire-events-guide.co.uk/ into data/events.yaml
# Strategy:
#  1) Try My Calendar JSON API (if enabled)
#  2) Fallback: crawl monthly pages (?cid=...&month=&yr=) and parse inline event blocks
#
# Usage:
#  python scripts/scrape_shropshire_events_guide.py --from 2025-06-01 --to 2026-12-31 --out data/events.yaml --merge

import argparse, os, re, sys, time
from datetime import date, datetime
from urllib.parse import urlparse, parse_qs, urljoin

import yaml
import requests
from bs4 import BeautifulSoup

BASE = "https://shropshire-events-guide.co.uk"
START_PAGE = f"{BASE}/"
UA = "Mozilla/5.0 (GitHub Actions; +https://github.com/) WhatsOn-Scraper/1.1"
TIMEOUT = 25
SLEEP = 0.6

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}

DATE_RE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{4})", re.I
)

def iso(d: date) -> str: return d.strftime("%Y-%m-%d")
def parse_date_token(tok: str) -> date:
    m = DATE_RE.search(tok)
    if not m: raise ValueError(f"no date in: {tok[:120]}")
    day, mon, yr = m.groups()
    return date(int(yr), MONTHS[mon.lower()], int(day))

def add_months(d: date, n: int) -> date:
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return date(y, m, 1)

def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/html,application/json"})
    return s

# ---------- 1) My Calendar JSON API (often disabled) ----------
def try_mc_api(sess: requests.Session, dfrom: date, dto: date):
    url = f"{BASE}/?my-calendar-api=events&format=json&from={iso(dfrom)}&to={iso(dto)}"
    try:
        r = sess.get(url, timeout=TIMEOUT)
        if r.status_code != 200:
            print(f"[mc-api] HTTP {r.status_code}"); return []
        data = r.json()
        raw = data if isinstance(data, list) else data.get("events", [])
        out = []
        for ev in raw:
            try:
                title = (ev.get("title") or ev.get("event_title") or "Untitled").strip()
                start = (ev.get("dtstart") or ev.get("event_begin") or ev.get("date"))[:10]
                end   = (ev.get("dtend") or ev.get("event_end") or start)[:10]
                href  = ev.get("link") or ev.get("event_link") or BASE
                loc   = ev.get("location") or ev.get("venue","") or ""
                desc  = (ev.get("description") or "").strip()
                out.append(dict(
                    summary=title, start=start, end=end,
                    location=loc.strip(), url=href,
                    categories="Shropshire,Shropshire Events Guide",
                    description=desc))
            except Exception:
                continue
        print(f"[mc-api] events: {len(out)}")
        return out
    except Exception as ex:
        print(f"[mc-api] unavailable: {ex}")
        return []

# ---------- 2) HTML monthly page parsing ----------
def discover_cid(sess: requests.Session) -> str | None:
    # Find the calendar id by inspecting the "Previous" link on the homepage
    try:
        r = sess.get(START_PAGE, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        prev = soup.find("a", string=lambda t: t and t.strip().lower()=="previous")
        if prev and prev.has_attr("href"):
            q = parse_qs(urlparse(prev["href"]).query)
            cid = q.get("cid", [None])[0]
            if cid:
                print(f"[html] discovered cid={cid}")
                return cid
    except Exception as ex:
        print(f"[html] cid discovery failed: {ex}")
    return None

def month_url(cid: str | None, y: int, m: int) -> str:
    if cid:
        return f"{START_PAGE}?cid={cid}&month={m}&yr={y}"
    return f"{START_PAGE}?month={m}&yr={y}"

def parse_month_inline_events(html: str, dfrom: date, dto: date) -> list[dict]:
    """Parse headings/blocks on the month page itself."""
    soup = BeautifulSoup(html, "lxml")
    events: list[dict] = []

    # Each event appears as an <h3> anchor followed by an <h2> title and a small block with times/location.
    for h3 in soup.find_all("h3"):
        block_nodes = []
        # Collect siblings until the next h3 (which starts the next event)
        for sib in h3.next_siblings:
            if getattr(sib, "name", None) == "h3":
                break
            block_nodes.append(sib)

        # Title is usually an <h2> right after <h3>
        title = None
        for node in block_nodes:
            if getattr(node, "name", None) in ("h2", "h3"):
                title = node.get_text(" ", strip=True)
                break
        if not title:
            # fallback: text of the h3 itself (it contains time/venue too)
            title = h3.get_text(" ", strip=True)

        # Flatten text of the block to find dates/times
        flat = " ".join(BeautifulSoup("".join(str(n) for n in block_nodes), "lxml").get_text(" ", strip=True).split())

        # Extract dates (may be a range with an en dash)
        m1 = DATE_RE.search(flat) or DATE_RE.search(h3.get_text(" ", strip=True))
        if not m1:
            continue
        start = parse_date_token(m1.group(0))
        # look for second date in the remaining text
        tail = flat[m1.end():]
        m2 = DATE_RE.search(tail)
        end = parse_date_token(m2.group(0)) if m2 else start
        if end < start:
            end = start

        # Filter by requested window
        if start > dto or end < dfrom:
            continue

        # Location heuristics
        location = ""
        # 1) a venue anchor often exists in the block (exclude "View Location"/"Map"/"More Information")
        for a in BeautifulSoup("".join(str(n) for n in block_nodes), "lxml").find_all("a", href=True):
            txt = (a.get_text(" ", strip=True) or "").strip()
            if not txt:
                continue
            low = txt.lower()
            if any(key in low for key in ("view location", "map ", "more information")):
                continue
            if len(txt) <= 60:
                location = txt
                break
        # 2) fallback: try to grab a line that looks like an address/town
        if not location:
            segs = flat.split("  ")
            for seg in segs:
                if any(t in seg for t in ("Shrewsbury", "Ludlow", "Oswestry", "Telford", "SY")):
                    location = seg.strip()
                    break

        # “More Information” URL if present
        url = ""
        for a in BeautifulSoup("".join(str(n) for n in block_nodes), "lxml").find_all("a", href=True):
            if (a.get_text(" ", strip=True) or "").strip().lower() == "more information":
                href = a["href"]
                url = href if href.startswith("http") else urljoin(BASE, href)
                break

        # Short description: first paragraph-like text with length > 40
        desc = ""
        for p in BeautifulSoup("".join(str(n) for n in block_nodes), "lxml").find_all(["p", "div"]):
            txt = (p.get_text(" ", strip=True) or "").strip()
            if len(txt) > 40:
                desc = txt[:600]
                break

        events.append(dict(
            summary=title.strip(),
            start=iso(start),
            end=iso(end),
            location=location.strip(),
            url=url.strip(),
            categories="Shropshire,Shropshire Events Guide",
            description=desc
        ))
    return events

def crawl_months(sess: requests.Session, dfrom: date, dto: date) -> list[dict]:
    evs: list[dict] = []
    cid = discover_cid(sess)
    cur = date(dfrom.year, dfrom.month, 1)
    endm = date(dto.year, dto.month, 1)
    seen = set()
    while cur <= endm:
        u = month_url(cid, cur.year, cur.month)
        try:
            r = sess.get(u, timeout=TIMEOUT)
            if r.status_code != 200:
                print(f"[html] {cur.year}-{cur.month:02d} -> HTTP {r.status_code}")
                cur = add_months(cur, 1); time.sleep(SLEEP); continue
            batch = parse_month_inline_events(r.text, dfrom, dto)
            for e in batch:
                key = (e["summary"], e["start"])
                if key in seen: continue
                seen.add(key); evs.append(e)
            print(f"[html] {cur.year}-{cur.month:02d} events: {len(batch)} (total {len(evs)})")
        except Exception as ex:
            print(f"[html] error {cur}: {ex}")
        cur = add_months(cur, 1)
        time.sleep(SLEEP)
    return evs

# ---------- YAML merge helpers ----------
def load_yaml(path: str) -> list[dict]:
    if not os.path.exists(path): return []
    try:
        y = yaml.safe_load(open(path, encoding="utf-8")) or {}
        lst = y.get("events", [])
        return lst if isinstance(lst, list) else []
    except Exception:
        return []

def dump_yaml(path: str, events: list[dict]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"events": events}, f, allow_unicode=True, sort_keys=False)

def merge_events(existing: list[dict], new: list[dict]) -> list[dict]:
    seen = {(e.get("summary","").strip(), e.get("start","").strip()) for e in existing}
    out = list(existing)
    added = 0
    for e in new:
        k = (e.get("summary","").strip(), e.get("start","").strip())
        if not k[0] or not k[1]: continue
        if k in seen: continue
        seen.add(k); out.append(e); added += 1
    out.sort(key=lambda x: (x.get("start",""), x.get("summary","").lower()))
    print(f"[merge] added {added} new; total {len(out)}")
    return out

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="dfrom", required=True, help="YYYY-MM-DD")
    ap.add_argument("--to", dest="dto", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", default="data/events.yaml")
    ap.add_argument("--merge", action="store_true")
    args = ap.parse_args()

    dfrom = datetime.strptime(args.dfrom, "%Y-%m-%d").date()
    dto   = datetime.strptime(args.dto, "%Y-%m-%d").date()

    sess = get_session()

    all_events = []
    # 1) JSON API (if the site allows it)
    all_events += try_mc_api(sess, dfrom, dto)
    # 2) Monthly HTML (inline blocks)
    all_events += crawl_months(sess, dfrom, dto)

    # De-dup within this run
    dedup = {}
    for e in all_events:
        if not e: continue
        dedup[(e["summary"], e["start"])] = e
    scraped = list(dedup.values())
    scraped.sort(key=lambda x: (x["start"], x["summary"].lower()))
    print(f"[total] scraped: {len(scraped)}")

    if args.merge:
        existing = load_yaml(args.out)
        merged = merge_events(existing, scraped)
        dump_yaml(args.out, merged)
    else:
        dump_yaml(args.out, scraped)

if __name__ == "__main__":
    sys.exit(main())

