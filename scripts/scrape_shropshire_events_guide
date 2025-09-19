#!/usr/bin/env python3
"""
Scrape events from https://shropshire-events-guide.co.uk/ into data/events.yaml.

Strategy (in order):
1) Try My Calendar export API (if enabled by the site admin).
2) Fallback: crawl monthly calendar pages (discover cid, then iterate months) and
   collect /mc-events/ links; parse each event page for title, date(s), location, blurb.

Usage:
  python scripts/scrape_shropshire_events_guide.py --from 2025-06-01 --to 2026-12-31 --out data/events.yaml --merge
"""
import argparse, os, re, sys, time, json
from datetime import date, datetime, timedelta
from urllib.parse import urlparse, parse_qs, urljoin
import yaml
import requests
from bs4 import BeautifulSoup

BASE = "https://shropshire-events-guide.co.uk"
START_PAGE = f"{BASE}/obt/"

UA = "Mozilla/5.0 (GitHub Actions; +https://github.com/) WhatsOn-Scraper/1.0"
TIMEOUT = 20
SLEEP = 0.7  # be polite

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}

DATE_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})", re.I)

def iso(d: date) -> str: return d.strftime("%Y-%m-%d")

def parse_date_str(s: str) -> date:
    m = DATE_RE.search(s)
    if not m: raise ValueError(f"no date in: {s[:120]}")
    day, mon, yr = m.groups()
    return date(int(yr), MONTHS[mon.lower()], int(day))

def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/html,application/json"})
    return s

# ---------- Approach 1: My Calendar API (if enabled) ----------
def try_mc_api(sess: requests.Session, dfrom: date, dto: date):
    # Based on plugin docs: ?my-calendar-api=events&format=json&from=YYYY-MM-DD&to=YYYY-MM-DD
    # Many sites do not enable this. We just try; on failure we return [] silently.
    url = f"{BASE}/?my-calendar-api=events&format=json&from={iso(dfrom)}&to={iso(dto)}"
    try:
        r = sess.get(url, timeout=TIMEOUT)
        if r.status_code != 200: return []
        data = r.json()
        events = []
        for ev in data if isinstance(data, list) else data.get("events", []):
            try:
                title = ev.get("title") or ev.get("event_title") or "Untitled"
                start = ev.get("dtstart") or ev.get("event_begin") or ev.get("date")
                end   = ev.get("dtend") or ev.get("event_end") or start
                href  = ev.get("link") or ev.get("event_link") or BASE
                loc   = ev.get("location") or ev.get("venue","")
                desc  = ev.get("description","")
                # normalize YYYY-MM-DD
                sdate = start[:10]
                edate = end[:10]
                events.append(dict(
                    summary=title.strip(),
                    start=sdate, end=edate,
                    location=(loc or "").strip(),
                    url=href, categories="Shropshire,Shropshire Events Guide",
                    description=(desc or "").strip()
                ))
            except Exception:
                continue
        if events:
            print(f"[mc-api] got {len(events)} events")
        return events
    except Exception as ex:
        print(f"[mc-api] unavailable: {ex}")
        return []

# ---------- Approach 2: HTML crawl ----------
def discover_calendar_id(sess: requests.Session) -> str | None:
    """Find cid value from the 'Previous' link on /obt/ monthly view."""
    try:
        r = sess.get(START_PAGE, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        prev = soup.find("a", string=lambda t: t and t.strip().lower()=="previous")
        if prev and prev.has_attr("href"):
            q = parse_qs(urlparse(prev["href"]).query)
            cid = q.get("cid", [None])[0]
            if cid: print(f"[html] discovered cid={cid}")
            return cid
    except Exception as ex:
        print(f"[html] cid discovery failed: {ex}")
    return None

def month_page_url(cid: str | None, year: int, month: int) -> str:
    if cid:
        return f"{START_PAGE}?cid={cid}&month={month}&yr={year}"
    return f"{START_PAGE}?month={month}&yr={year}"

def extract_event_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/mc-events/" in href:
            links.add(href if href.startswith("http") else urljoin(BASE, href))
    return sorted(links)

def parse_event_page(sess: requests.Session, url: str, dfrom: date, dto: date) -> dict | None:
    try:
        r = sess.get(url, timeout=TIMEOUT)
        if r.status_code != 200: return None
        soup = BeautifulSoup(r.text, "lxml")

        # Title
        h1 = soup.find(["h1","h2"])
        title = (h1.get_text(strip=True) if h1 else "Untitled").strip()

        # Flatten text for date extraction
        flat = " ".join(soup.get_text(separator=" ", strip=True).split())

        # Handle single or range dates e.g. "All Day - 30th May 2025" or "09:00 - 22:00 26th July 2025 – 10th August 2025"
        dates = DATE_RE.findall(flat)
        if not dates:
            return None
        # first date:
        s1 = DATE_RE.search(flat)
        start = parse_date_str(s1.group(0))
        end = start
        # look for a second date after an en dash/hyphen
        tail = flat[s1.end():]
        s2 = DATE_RE.search(tail)
        if s2:
            end = parse_date_str(s2.group(0))
            if end < start: end = start

        # crude location: look for "View Location" or "Map <location>" block
        loc = ""
        for tag in soup.find_all(["a","strong","div","p"]):
            t = tag.get_text(" ", strip=True)
            if "View Location" in t or t.startswith("Map "):
                loc = t.replace("View Location","").strip()
                break
        if not loc:
            # fallback: first line after title that looks like a venue (contains town or postcode)
            ps = soup.find_all("p")
            for p in ps[:5]:
                t = p.get_text(" ", strip=True)
                if any(x in t for x in ("Shrewsbury","Oswestry","Ludlow","Telford","SY")):
                    loc = t[:120]
                    break

        # description: first meaningful paragraph
        desc = ""
        for p in soup.find_all("p"):
            txt = p.get_text(" ", strip=True)
            if len(txt) > 40:
                desc = txt[:600]
                break

        if start > dto or end < dfrom:
            return None

        return dict(
            summary=title,
            start=iso(start),
            end=iso(end),
            location=loc,
            url=url,
            categories="Shropshire,Shropshire Events Guide",
            description=desc
        )
    except Exception:
        return None

def crawl_html(sess: requests.Session, dfrom: date, dto: date) -> list[dict]:
    events: list[dict] = []
    cid = discover_calendar_id(sess)
    # iterate month grid pages in range
    cur = date(dfrom.year, dfrom.month, 1)
    endm = date(dto.year, dto.month, 1)
    seen_links = set()
    while cur <= endm:
        u = month_page_url(cid, cur.year, cur.month)
        try:
            r = sess.get(u, timeout=TIMEOUT)
            if r.status_code != 200:
                cur = add_months(cur, 1); time.sleep(SLEEP); continue
            links = extract_event_links(r.text)
            for href in links:
                if href in seen_links: continue
                seen_links.add(href)
                ev = parse_event_page(sess, href, dfrom, dto)
                if ev: events.append(ev)
                time.sleep(SLEEP)
        except Exception:
            pass
        cur = add_months(cur, 1)
        time.sleep(SLEEP)
    if events:
        print(f"[html] scraped {len(events)} events")
    return events

def add_months(d: date, n: int) -> date:
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return date(y, m, 1)

# ---------- YAML merge ----------
def load_yaml(path: str) -> list[dict]:
    if not os.path.exists(path): return []
    try:
        y = yaml.safe_load(open(path, encoding="utf-8")) or {}
        evs = y.get("events", [])
        return evs if isinstance(evs, list) else []
    except Exception:
        return []

def dump_yaml(path: str, events: list[dict]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"events": events}, f, allow_unicode=True, sort_keys=False)

def uniq_key(e: dict) -> tuple:
    return (e.get("summary","").strip(), e.get("start","").strip())

def merge_events(existing: list[dict], new: list[dict]) -> list[dict]:
    seen = {uniq_key(e) for e in existing}
    out = list(existing)
    added = 0
    for e in new:
        k = uniq_key(e)
        if not k[0] or not k[1]: continue
        if k in seen: continue
        seen.add(k); out.append(e); added += 1
    out.sort(key=lambda x: (x.get("start",""), x.get("summary","").lower()))
    print(f"[merge] added {added} new; total {len(out)}")
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="dfrom", required=True, help="YYYY-MM-DD")
    ap.add_argument("--to", dest="dto", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", default="data/events.yaml")
    ap.add_argument("--merge", action="store_true", help="merge with existing YAML instead of overwriting")
    args = ap.parse_args()

    dfrom = datetime.strptime(args.dfrom, "%Y-%m-%d").date()
    dto   = datetime.strptime(args.dto, "%Y-%m-%d").date()

    sess = get_session()

    all_events = []
    # 1) Try JSON API
    api_events = try_mc_api(sess, dfrom, dto)
    all_events.extend(api_events)

    # 2) Fallback HTML
    html_events = crawl_html(sess, dfrom, dto)
    all_events.extend(html_events)

    # de-dup within scrape batch
    dedup = {}
    for e in all_events:
        if not e: continue
        dedup[uniq_key(e)] = e
    scraped = list(dedup.values())
    scraped.sort(key=lambda x: (x["start"], x["summary"].lower()))
    print(f"[total] {len(scraped)} scraped events")

    if args.merge:
        existing = load_yaml(args.out)
        merged = merge_events(existing, scraped)
        dump_yaml(args.out, merged)
    else:
        dump_yaml(args.out, scraped)

if __name__ == "__main__":
    sys.exit(main())
