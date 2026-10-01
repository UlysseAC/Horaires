#!/usr/bin/env python3
"""
Genere deux fichiers .ics a partir de l'horaire ISPSO/UNIGE (farma-horaires.unige.ch) :

  - horaire.ics        : horaire complet, inchange (celui que tes amis utilisent)
  - horaire-perso.ics   : meme horaire, SANS les cours listes dans EXCLUDE_CODES

Configuration : modifier les constantes ci-dessous.
Usage : python3 generate.py
"""

import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

# ----------------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------------

LEVEL = "BIOMD1"          # Ton niveau d'etude (visible dans l'URL du site)
CODE = "all"              # Filtre code de cours cote API, "all" = tous
ROOM = "all"              # Filtre salle, "all" = toutes
TEACHERS = "all"          # Filtre enseignant, "all" = tous

# Codes de cours a exclure UNIQUEMENT dans la version personnelle
# (le fichier horaire.ics complet, utilise par tes amis, n'est pas touche)
EXCLUDE_CODES = {
    "14HS033A",  # Carrieres Biomed - Automne
    "14H001BM",  # Decouverte et conception des medicaments
    "14HS031",   # Health economics and clinical outcomes
}

MONTHS_BACK = 2           # Combien de mois en arriere recuperer
MONTHS_AHEAD = 10         # Combien de mois en avant recuperer

CALENDAR_NAME_FULL = "Horaire UNIGE"
CALENDAR_NAME_PERSO = "Horaire UNIGE (perso)"

OUTPUT_FULL = "horaire.ics"
OUTPUT_PERSO = "horaire-perso.ics"

API = "https://farma-horaires.unige.ch/get/data"

# ----------------------------------------------------------------------------


def fetch_events(start, end):
    """Interroge l'API et retourne la liste brute des evenements."""
    params = {
        "levels": LEVEL,
        "code": CODE,
        "room": ROOM,
        "teachers": TEACHERS,
        "cachebuster": str(int(datetime.now().timestamp() * 1000)),
        "start": start.strftime("%Y-%m-%dT00:00:00+02:00"),
        "end": end.strftime("%Y-%m-%dT00:00:00+02:00"),
        "timeZone": "Europe/Zurich",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def esc(text):
    """Echappe un texte pour le format iCalendar."""
    if text is None:
        return ""
    return (str(text)
            .replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\n", "\\n"))


def fold(line):
    """Replie les lignes a 75 octets comme l'exige la RFC 5545."""
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
    """Parse une date ISO de l'API (format ...Z) en datetime UTC."""
    s = s.replace("Z", "").split(".")[0]
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def build_ics(events, calendar_name, exclude_codes=None):
    """Construit le contenu ICS. exclude_codes: set de codes a sauter, ou None."""
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

        # --- filtre des cours facultatifs (version perso uniquement) ---
        if code in exclude_codes:
            continue

        name = course.get("name") or "Cours"
        title = f"{code} - {name}" if code else name

        rooms = ev.get("rooms") or []
        rooms = list(dict.fromkeys(r for r in rooms if r))
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


def main():
    today = datetime.now()
    start = today - timedelta(days=30 * MONTHS_BACK)
    end = today + timedelta(days=30 * MONTHS_AHEAD)

    print(f"Recuperation : {start.date()} -> {end.date()} (niveau {LEVEL})")
    events = fetch_events(start, end)
    print(f"{len(events)} evenements recus")

    # --- fichier complet (pour tes amis, inchange) ---
    ics_full = build_ics(events, CALENDAR_NAME_FULL, exclude_codes=None)
    with open(OUTPUT_FULL, "w", encoding="utf-8", newline="") as f:
        f.write(ics_full)
    print(f"{OUTPUT_FULL} ecrit ({ics_full.count('BEGIN:VEVENT')} evenements)")

    # --- fichier personnel (filtre) ---
    ics_perso = build_ics(events, CALENDAR_NAME_PERSO, exclude_codes=EXCLUDE_CODES)
    with open(OUTPUT_PERSO, "w", encoding="utf-8", newline="") as f:
        f.write(ics_perso)
    print(f"{OUTPUT_PERSO} ecrit ({ics_perso.count('BEGIN:VEVENT')} evenements)")


if __name__ == "__main__":
    main()
