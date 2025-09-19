#!/usr/bin/env python3
# Build whatson-shropshire-cheshire-northwales.ics from data/events.yaml
# Safe for Apple Calendar:
# - Never writes empty URL/CATEGORIES/DESCRIPTION properties
# - All-day events use exclusive DTEND (RFC 5545)
# - CRLF line endings
# - Stable UIDs (summary+year)
# - Window: 2025-06-01 .. 2026-12-31

import os, re, unicodedata, sys
from datetime import datetime, timedelta, date
from typing import List, Dict

try:
    import yaml
except Exception as ex:
    print(f"::error::PyYAML not installed: {ex}")
    sys.exit(1)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IN_YAML   = os.path.join(REPO_ROOT, "data", "events.yaml")
OUT_ICS   = os.path.join(REPO_ROOT, "whatson-shropshire-cheshire-northwales.ics")

CAL_NAME = "What’s On — Shropshire • Cheshire • North Wales"
PRODID   = "-//WhatsOn Builder//EN"
DTSTAMP  = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

WINDOW_START = date(2025, 6, 1)
WINDOW_END   = date(2026, 12, 31)
EOL = "\r\n"  # Apple-friendly line endings

def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode("ascii")
    t = re.sub(r"[^a-zA-Z0-9]+","-",t).strip("-").lower()
    return re.sub(r"-{2,}","-",t) or "event"

def esc(s: str) -> str:
    # RFC5545 text escaping
    return str(s).replace("\\","\\\\").replace(",","\\,").replace(";","\\;").replace("\n","\\n")

def load_events(path: str) -> List[Dict]:
    if not os.path.exists(path):
        print(f"[warn] missing file: {path} (0 events)")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            y = yaml.safe_load(f) or {}
        evs = y.get("events", [])
        if not isinstance(evs, list):
            print("[warn] 'events' key is not a list; ignoring.")
            return []
        return evs
    except Exception as ex:
        print(f"[warn] YAML parse error in {path}: {ex}")
        return []

def parse_ymd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()

def in_window(s: date, e: date) -> bool:
    return not (e < WINDOW_START or s > WINDOW_END)

def build_vevent(e: Dict) -> str:
    try:
        summary   = e["summary"]
        start_str = e["start"]
    except KeyError as ex:
        print(f"[warn] missing required field {ex} -> skipping: {e}")
        return ""

    end_str   = e.get("end", start_str)
    location  = e.get("location","")
    url       = (e.get("url","") or "").strip()
    cats      = (e.get("categories","") or "").strip().strip(",")
    desc      = e.get("description","") or ""

    try:
        s = parse_ymd(start_str)
        e_date = parse_ymd(end_str)
    except Exception as ex:
        print(f"[warn] bad date(s) in '{summary}': {ex}; skipping")
        return ""
    if e_date < s: e_date = s
    if not in_window(s, e_date):  # outside window
        return ""

    dtend = (e_date + timedelta(days=1)).strftime("%Y%m%d")
    uid = f"{slugify(summary)}-{s.year}@whatson.local"

    lines = []
    lines.append("BEGIN:VEVENT")
    lines.append(f"UID:{uid}")
    lines.append(f"DTSTAMP:{DTSTAMP}")
    lines.append(f"DTSTART;VALUE=DATE:{s.strftime('%Y%m%d')}")
    lines.append(f"DTEND;VALUE=DATE:{dtend}")
    lines.append(f"SUMMARY:{esc(summary)}")
    if location:
        lines.append(f"LOCATION:{esc(location)}")

    # DESCRIPTION (only if there is text or URL)
    desc_parts = []
    if desc:
        desc_parts.append(esc(desc))
    if url:
        desc_parts.append("More: " + url)
    if desc_parts:
        lines.append("DESCRIPTION:" + "\\n".join(desc_parts))

    if url:
        lines.append(f"URL:{url}")
    if cats:
        lines.append(f"CATEGORIES:{esc(cats)}")

    lines.append("STATUS:CONFIRMED")
    lines.append("TRANSP:TRANSPARENT")
    lines.append("END:VEVENT")
    return EOL.join(lines)

def main() -> int:
    evs = load_events(IN_YAML)

    cleaned = []
    for e in evs:
        try:
            s = parse_ymd(e["start"])
            e_end = parse_ymd(e.get("end", e["start"]))
            cleaned.append((s, e_end, e))
        except Exception as ex:
            print(f"[warn] skipping event due to date parse: {ex} -> {e}")
    cleaned.sort(key=lambda t: t[0])

    vevents = []
    seen = set()
    for s, e_end, e in cleaned:
        ve = build_vevent(e)
        if not ve:
            continue
        key = (e.get("summary",""), s.isoformat())
        if key in seen:
            continue
        seen.add(key)
        vevents.append(ve)

    header = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-TIMEZONE:Europe/London",
        f"X-WR-CALNAME:{esc(CAL_NAME)}",
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:PT12H",
    ]
    footer = ["END:VCALENDAR"]

    vcal = EOL.join(header + vevents + footer) + EOL  # final EOL

    with open(OUT_ICS, "w", encoding="utf-8", newline="") as f:
        f.write(vcal)

    print(f"Wrote {OUT_ICS} with {len(vevents)} events.")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as ex:
        print(f"::error::Unexpected error in build: {ex}")
        sys.exit(1)

