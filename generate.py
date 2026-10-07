#!/usr/bin/env python3
"""
Genere deux fichiers .ics a partir de l'horaire ISPSO/UNIGE (farma-horaires.unige.ch) :

  - horaire.ics        : horaire complet (celui que tes amis utilisent)
  - horaire-perso.ics  : meme horaire, SANS les cours listes dans EXCLUDE_CODES

Differences avec la version precedente :
  - l'API est interrogee semaine par semaine (comme le fait le site), au lieu
    d'une seule requete sur ~12 mois qui peut revenir vide
  - si l'API ne renvoie AUCUN evenement, les fichiers existants ne sont pas
    ecrases et le script se termine en erreur (croix rouge dans GitHub Actions)

Usage : python3 generate.py
"""

import json
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

# ----------------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------------

LEVEL = "BIOMD1"          # Ton niveau d'etude
CODE = "all"
ROOM = "all"
TEACHERS = "all"

# Cours exclus UNIQUEMENT dans la version perso.
# Attention : le cours "Decouverte et conception des medicaments" apparait
# maintenant sous le code 14H001 (avant : 14H001BM). On garde les deux.
EXCLUDE_CODES = {
    "14HS033A",  # Carrieres Biomed - Automne
    "14H001",    # Decouverte et conception des medicaments
    "14H001BM",  # Decouverte et conception des medicaments (ancienne variante)
    "14HS031",   # Health economics and clinical outcomes
}

WEEKS_BACK = 8            # semaines passees a recuperer
WEEKS_AHEAD = 35          # semaines futures a recuperer

CALENDAR_NAME_FULL = "Horaire UNIGE"
CALENDAR_NAME_PERSO = "Horaire UNIGE (perso)"

OUTPUT_FULL = "horaire.ics"
OUTPUT_PERSO = "horaire-perso.ics"

API = "https://farma-horaires.unige.ch/get/data"

# ----------------------------------------------------------------------------


def zurich_offset(d):
    """Decalage Europe/Zurich approximatif : +02:00 de fin mars a fin octobre."""
    return "+02:00" if 3 < d.month < 10 or (d.month == 3 and d.day >= 28) \
        or (d.month == 10 and d.day < 26) else "+01:00"


def fetch_week(monday):
    """Recupere les evenements d'une semaine (lundi -> lundi suivant)."""
    nxt = monday + timedelta(days=7)
    params = {
        "levels": LEVEL,
        "code": CODE,
        "room": ROOM,
        "teachers": TEACHERS,
        "cachebuster": str(int(datetime.now().timestamp() * 1000)),
        "start": monday.strftime("%Y-%m-%dT00:00:00") + zurich_offset(monday),
        "end": nxt.strftime("%Y-%m-%dT00:00:00") + zurich_offset(nxt),
        "timeZone": "Europe/Zurich",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    })
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, list):
                raise ValueError(f"reponse inattendue: {str(data)[:200]}")
            return data
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"semaine du {monday.date()} : {last_err}")


def fetch_all():
    today = datetime.now().date()
    first_monday = today - timedelta(days=today.weekday()) - timedelta(weeks=WEEKS_BACK)
    weeks = WEEKS_BACK + WEEKS_AHEAD
    events, seen = [], set()
    for i in range(weeks):
        monday = first_monday + timedelta(weeks=i)
        for ev in fetch_week(monday):
            uid = str(ev.get("id", ""))
            if uid and uid not in seen:
                seen.add(uid)
                events.append(ev)
        time.sleep(0.2)
    return events


def esc(text):
    if text is None:
        return ""
    return (str(text)
            .replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\n", "\\n"))


def fold(line):
    """Replie les lignes a 75 octets (RFC 5545)."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > 73:
            out.append(cur.decode("utf-8"))
            cur = b" " + b
        else:
            cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n".join(out)


def parse_dt(s):
    s = s.replace("Z", "").split(".")[0]
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def build_ics(events, calendar_name, exclude_codes=None):
    exclude_codes = exclude_codes or set()
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//horaire-unige//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(calendar_name)}",
        "X-WR-TIMEZONE:Europe/Zurich",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]

    seen = set()
    for ev in events:
        uid = str(ev.get("id", ""))
        if not uid or uid in seen:
            continue
        seen.add(uid)

        course = ev.get("course") or {}
        code = course.get("code") or ""
        if code in exclude_codes:
            continue

        name = course.get("name") or "Cours"
        title = f"{code} - {name}" if code else name

        rooms = list(dict.fromkeys(r for r in (ev.get("rooms") or []) if r))
        location = ", ".join(rooms)

        teachers = []
        for t in (ev.get("teachers") or []):
            full = t.get("fullName") or t.get("teacher") or ""
            if full and full.lower() not in ("non defini", "non défini"):
                teachers.append(full)
        teachers = list(dict.fromkeys(teachers))

        desc_parts = []
        if teachers:
            desc_parts.append("Enseignant(s) : " + ", ".join(teachers))
        if course.get("thematic"):
            desc_parts.append("Thematique : " + course["thematic"])
        if course.get("description"):
            desc_parts.append(course["description"])
        links = (ev.get("extendedProps") or {}).get("links") or {}
        if links.get("course"):
            desc_parts.append(links["course"])
        description = "\n".join(desc_parts)

        try:
            dtstart = parse_dt(ev["start"]).strftime("%Y%m%dT%H%M%SZ")
            dtend = parse_dt(ev["end"]).strftime("%Y%m%dT%H%M%SZ")
        except (KeyError, ValueError):
            continue

        lines += [
            "BEGIN:VEVENT",
            f"UID:unige-{uid}@farma-horaires",
            f"DTSTAMP:{now}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            fold(f"SUMMARY:{esc(title)}"),
        ]
        if location:
            lines.append(fold(f"LOCATION:{esc(location)}"))
        if description:
            lines.append(fold(f"DESCRIPTION:{esc(description)}"))
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write(path, content):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)


def main():
    print(f"Recuperation semaine par semaine (niveau {LEVEL}, "
          f"{WEEKS_BACK} sem. passees, {WEEKS_AHEAD} sem. a venir)")
    events = fetch_all()
    print(f"{len(events)} evenements recus")

    if not events:
        print("ERREUR : l'API n'a renvoye aucun evenement. "
              "Les fichiers existants sont conserves.", file=sys.stderr)
        sys.exit(1)

    ics_full = build_ics(events, CALENDAR_NAME_FULL)
    write(OUTPUT_FULL, ics_full)
    print(f"{OUTPUT_FULL} ecrit ({ics_full.count('BEGIN:VEVENT')} evenements)")

    ics_perso = build_ics(events, CALENDAR_NAME_PERSO, exclude_codes=EXCLUDE_CODES)
    write(OUTPUT_PERSO, ics_perso)
    print(f"{OUTPUT_PERSO} ecrit ({ics_perso.count('BEGIN:VEVENT')} evenements)")


if __name__ == "__main__":
    main()
