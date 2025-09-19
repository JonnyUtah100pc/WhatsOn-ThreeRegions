#!/usr/bin/env python3
# Build whatson-shropshire-cheshire-northwales.ics from data/events.yaml
# - All-day events with exclusive DTEND (RFC5545)
# - Stable UID per (summary + year)
# - Filters to window: 2025-06-01 .. 2026-12-31
# - Sorted by start date

import os, re, unicodedata, yaml
from datetime import datetime, timedelta, date
from typing import List, Dict

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IN_YAML   = os.path.join(REPO_ROOT, "data", "events.yaml")
OUT_ICS   = os.path.join(REPO_ROOT, "whatson-shropshire-cheshire-northwales.ics")

CAL_NAME = "What’s On — Shropshire • Cheshire • North Wales"
PRODID   = "-//WhatsOn Builder//EN"
DTSTAMP  = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

WINDOW_START = date(2025, 6, 1)
WINDOW_END   = date(2026, 12, 31)

def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode("ascii")
    t = re.sub(r"[^a-zA-Z0-9]+","-",t).strip("-").lower()
    return re.sub(r"-{2,}","-",t) or "event"

def esc(s: str) -> str:
    return str(s).replace("\\","\\\\").replace(",","\\,").replace(";","\\;").replace("\n","\\n")

def load_events(path: str) -> List[Dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            y = yaml.safe_load(f) or {}
        evs = y.get("events", [])
        return evs if isinstance(evs, list) else []
    except Exception as ex:
        print(f"[warn] YAML parse error in {path}: {ex}")
        return []

def parse_ymd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()

def in_window(s: date, e: date) -> bool:
    return not (e < WINDOW_START or s > WINDOW_END)

def build_vevent(e: Dict) -> str:
    summary   = e["summary"]
    start_str = e["start"]
    end_str   = e.get("end", start_str)
    location  = e.get("location","")
    url       = e.get("url","")
    cats      = e.get("categories","")
    desc      = e.get("description","")

    s = parse_ymd(start_str)
    e_date = parse_ymd(end_str)
    if e_date < s: e_date = s

    if not in_window(s, e_date):
        return ""  # skip outside window

    dtend = (e_date + timedelta(days=1)).strftime("%Y%m%d")
    uid = f"{slugify(summary)}-{s.year}@whatson.local"

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{DTSTAMP}",
        f"DTSTART;VALUE=DATE:{s.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{dtend}",
        f"SUMMARY:{esc(summary)}",
        f"LOCATION:{esc(location)}",
        f"DESCRIPTION:{esc(desc)}{('\\nMore: ' + url) if url else ''}",
        f"URL:{url}" if url else "URL:",
        f"CATEGORIES:{esc(cats)}" if cats else "CATEGORIES:",
        "STATUS:CONFIRMED",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]
    return "\n".join(lines)

def main():
    evs = load_events(IN_YAML)

    # normalise + sort
    cleaned = []
    for e in evs:
        try:
            s = parse_ymd(e["start"])
            e_end = parse_ymd(e.get("end", e["start"]))
            cleaned.append((s, e_end, e))
        except Exception:
            continue
    cleaned.sort(key=lambda t: t[0])

    vevents = []
    seen = set()
    for s, e_end, e in cleaned:
        ve = build_vevent(e)
        if not ve: 
            continue
        # dedupe by (summary, start)
        key = (e["summary"], s.isoformat())
        if key in seen:
            continue
        seen.add(key)
        vevents.append(ve)

    vcal = "\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-TIMEZONE:Europe/London",
        f"X-WR-CALNAME:{esc(CAL_NAME)}",
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:PT12H",
        *vevents,
        "END:VCALENDAR",
    ])

    with open(OUT_ICS, "w", encoding="utf-8") as f:
        f.write(vcal)

    print(f"Wrote {OUT_ICS} with {len(vevents)} events.")

if __name__ == "__main__":
    main()
