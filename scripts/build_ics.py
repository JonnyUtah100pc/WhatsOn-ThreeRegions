#!/usr/bin/env python3
# Build whatson-shropshire-cheshire-northwales.ics from data/events.yaml

import os, re, unicodedata, yaml
from datetime import datetime, timedelta

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IN_YAML   = os.path.join(REPO_ROOT, "data", "events.yaml")
OUT_ICS   = os.path.join(REPO_ROOT, "whatson-shropshire-cheshire-northwales.ics")

CAL_NAME = "What’s On — Shropshire • Cheshire • North Wales"
PRODID   = "-//WhatsOn Builder//EN"
DTSTAMP  = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode("ascii")
    t = re.sub(r"[^a-zA-Z0-9]+","-",t).strip("-").lower()
    return re.sub(r"-{2,}","-",t) or "event"

def esc(s: str) -> str:
    return str(s).replace("\\","\\\\").replace(",","\\,").replace(";","\\;").replace("\n","\\n")

def load_events(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        y = yaml.safe_load(f) or {}
    return y.get("events", [])

def vevent(e: dict) -> str:
    summary   = e["summary"]
    start_str = e["start"]
    end_str   = e.get("end", start_str)
    location  = e.get("location","")
    url       = e.get("url","")
    cats      = e.get("categories","")
    desc      = e.get("description","")

    s = datetime.strptime(start_str, "%Y-%m-%d").date()
    e_date = datetime.strptime(end_str, "%Y-%m-%d").date()
    if e_date < s: e_date = s
    dtend = (e_date + timedelta(days=1)).strftime("%Y%m%d")

    uid = f"{slugify(summary)}-{s.year}@whatson.example"
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
    events = load_events(IN_YAML)
    vevents = [vevent(e) for e in events]
    cal = "\n".join([
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
        f.write(cal)
    print(f"Wrote {OUT_ICS} with {len(vevents)} events.")

if __name__ == "__main__":
    main()
