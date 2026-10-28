#!/usr/bin/env python3
"""
Nachrichtenlage – baut das News-Dashboard.

Ruft alle Quellen aus feeds.json ab, entfernt Dubletten, erkennt Themen,
über die mehrere Quellen berichten, und schreibt eine eigenständige
HTML-Seite nach site/index.html.

Mit API-Schlüssel (Umgebungsvariable ANTHROPIC_API_KEY) zusätzlich:
- Claude wählt die wichtigsten Meldungen aus und schlägt Instagram-Themen
  mit Überschrift und Subline vor (alle AI_INTERVAL_HOURS Stunden neu)
- Claude recherchiert einmal täglich per Websuche anstehende Quartalszahlen
  und ergänzt damit die festen Termine aus termine.json

Nur Python-Standardbibliothek, keine Installation nötig.
"""

import json
import os
import re
import sys
import html
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
FEEDS_FILE = os.path.join(ROOT, "feeds.json")
TEMPLATE_FILE = os.path.join(ROOT, "template.html")
TERMINE_FILE = os.path.join(ROOT, "termine.json")
OUT_DIR = os.path.join(ROOT, "site")

MAX_AGE_HOURS = 36          # ältere Meldungen werden verworfen
MAX_PER_FEED = 40           # höchstens so viele Meldungen pro Quelle
SUBLINE_CHARS = 220         # Länge der Subline
TIMEOUT = 20                # Sekunden pro Quelle
USER_AGENT = "Mozilla/5.0 (compatible; Nachrichtenlage/1.0; persönliches News-Dashboard)"

AI_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")              # Auswahl + Themenvorschläge
TERMINE_MODEL = os.environ.get("CLAUDE_TERMINE_MODEL", "claude-haiku-5-5")  # tägliche Termin-Recherche
AI_PICKS = 8
AI_SUGGESTIONS = 5
AI_INTERVAL_HOURS = float(os.environ.get("AI_INTERVAL_HOURS", "3"))
TERMINE_INTERVAL_HOURS = 24
TERMINE_DAYS = 14
PAGES_URL = os.environ.get("PAGES_URL", "").rstrip("/")   # Adresse der veröffentlichten Seite (setzt GitHub)

# Gewichtung der Kategorien bei "Heute im Fokus": Wirtschaft und Märkte zählen mehr
CATEGORY_WEIGHT = {"maerkte": 1.4, "konjunktur": 1.4, "notenbanken": 1.4, "international": 1.1, "allgemein": 0.7}

try:
    from zoneinfo import ZoneInfo
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:
    BERLIN = timezone(timedelta(hours=1))


# ---------------------------------------------------------------- Abruf

def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def child(el, *names):
    for c in el:
        if local(c.tag) in names:
            return c
    return None


def text_of(el):
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def clean(s):
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def shorten(s, n):
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;:–-") + " …"


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        d = None
    if d is None:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def parse_feed(raw, feed):
    root = ET.fromstring(raw)
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        title = clean(text_of(child(el, "title")))
        if not title:
            continue

        link = ""
        for c in el:
            if local(c.tag) == "link":
                href = c.get("href")
                rel = c.get("rel", "alternate")
                if href and rel == "alternate":
                    link = href.strip()
                    break
                if not href and text_of(c):
                    link = text_of(c)
                    break
        if not link:
            g = child(el, "guid", "id")
            if g is not None and text_of(g).startswith("http"):
                link = text_of(g)

        summary = clean(text_of(child(el, "description", "summary", "content", "encoded")))
        if summary.lower().startswith(title.lower()):
            summary = summary[len(title):].lstrip(" .:–-")

        date = None
        for name in ("pubdate", "published", "updated", "date", "issued"):
            date = parse_date(text_of(child(el, name)))
            if date:
                break

        items.append({
            "title": title,
            "subline": shorten(summary, SUBLINE_CHARS),
            "link": link,
            "date": date,
            "source": feed["name"],
            "category": feed["category"],
        })
        if len(items) >= MAX_PER_FEED:
            break
    return items


def load_feed(feed):
    try:
        items = parse_feed(fetch(feed["url"]), feed)
        return feed, items, None
    except Exception as e:
        return feed, [], f"{type(e).__name__}: {str(e)[:120]}"


# ---------------------------------------------------------- Themen finden

STOP = set("""
aber alle allem allen aller alles also auch auf aus beim bei bis bereits damit dann
darf dass dabei davon dem den der des die dies diese diesem diesen dieser doch durch
eine einem einen einer eines erst etwa fuer für gegen geht gibt hat hatte haben heute
hier ihre ihren immer jetzt kann kein keine mehr mit muss nach neue neuen neuer noch
nun nur oder ohne schon sein seine sich sie sind soll sollen ueber über um und uns
unter viel vom von vor war waren was weil weiter wenn werden wie wieder will wird wir
zum zur zwei drei jahr jahre prozent mrd mio euro dollar laut news live ticker
the and for with from that this have has are was were will into after over amid
says said new more than about what when how why its their your you not but
stock stocks market markets report could would should may might live update
aktie aktien börse boerse anleger anlegern investoren kurs kurse
""".split())


def tokens(title):
    words = re.findall(r"[A-Za-zÄÖÜäöüß0-9]+", title)
    out = set()
    for w in words:
        lw = w.lower()
        if lw in STOP or len(lw) < 3 or lw.isdigit():
            continue
        out.add(lw[:6])   # grober Wortstamm: "Zinsen"/"Zinsentscheid" -> "zinsen"
    return out


def similar(a, b):
    shared = len(a & b)
    if shared >= 3:
        return True
    if shared >= 2:
        return shared / max(1, len(a | b)) >= 0.2
    return False


def find_topics(items, limit=6):
    clusters = []
    for it in items:
        tk = it["_tokens"]
        if len(tk) < 2:
            continue
        home = None
        for cl in clusters:
            if similar(tk, cl[0]["_tokens"]):   # nur mit der ersten Meldung vergleichen, sonst verkettet sich alles
                home = cl
                break
        if home is None:
            clusters.append([it])
        else:
            home.append(it)

    topics = []
    for cl in clusters:
        sources = {m["source"].split(" ")[0] for m in cl}   # tagesschau + tagesschau Wirtschaft zählt einmal
        if len(sources) < 2:
            continue
        cl.sort(key=lambda m: (len(m["subline"]) > 0, m["date"] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        topics.append({
            "lead": cl[0]["id"],
            "items": [m["id"] for m in cl],
            "sources": sorted({m["source"] for m in cl}),
            "count": len(sources),
            "score": round(len(sources) * CATEGORY_WEIGHT.get(cl[0]["category"], 1.0), 2),
            "newest": max((m["date"] for m in cl if m["date"]), default=None),
        })
    topics.sort(key=lambda t: (t["score"], t["newest"] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    for t in topics:
        t["newest"] = t["newest"].isoformat() if t["newest"] else None
    return topics[:limit]


# ------------------------------------------------------------- Termine

def today_berlin():
    return datetime.now(BERLIN).date()


def load_manual_termine():
    try:
        with open(TERMINE_FILE, encoding="utf-8") as f:
            raw = json.load(f).get("termine", [])
    except FileNotFoundError:
        return []
    out = []
    for t in raw:
        if t.get("datum") and t.get("unternehmen"):
            out.append({
                "datum": t["datum"], "unternehmen": t["unternehmen"].strip(),
                "region": (t.get("region") or "").upper(), "zeit": t.get("zeit", ""),
                "hinweis": t.get("hinweis", ""), "bestaetigt": bool(t.get("bestaetigt", True)),
                "quelle": "fest",
            })
    return out


def merge_termine(manual, auto):
    start = today_berlin()
    end = start + timedelta(days=TERMINE_DAYS)
    seen, out = set(), []
    # Reihenfolge = Vorrang: bestätigte feste, bestätigte recherchierte, dann unbestätigte
    cands = manual + [dict(a, quelle="auto") for a in (auto or [])]
    cands.sort(key=lambda t: (not t["bestaetigt"], t["quelle"] != "fest"))
    for t in cands:
        try:
            d = datetime.strptime(t["datum"], "%Y-%m-%d").date()
        except Exception:
            continue
        if not (start <= d <= end):
            continue
        key = (t["datum"], re.sub(r"\W+", "", t["unternehmen"].lower())[:8])
        name_key = re.sub(r"\W+", "", t["unternehmen"].lower())[:8]
        # ein Unternehmen nur einmal; feste Termine (zuerst in der Liste) haben Vorrang
        if key in seen or ("any", name_key) in seen:
            continue
        seen.update({key, ("any", name_key)})
        out.append(t)
    region_order = {"DE": 0, "EU": 1, "US": 2}
    out.sort(key=lambda t: (t["datum"], region_order.get(t["region"], 3), t["unternehmen"].lower()))
    return out


# ------------------------------------------------------------------ KI

def claude(model, prompt, max_tokens, tools=None, timeout=120):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    payload = {"model": model, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    if tools:
        payload["tools"] = tools
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=json.dumps(payload).encode(), method="POST",
        headers={"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def extract_json(text, opener):
    closer = "]" if opener == "[" else "}"
    text = re.sub(r"```(?:json)?", "", text)
    return json.loads(text[text.find(opener): text.rfind(closer) + 1])


def previous_ai():
    """Letzte KI-Ergebnisse von der veröffentlichten Seite holen, um Kosten zu sparen."""
    if not PAGES_URL:
        return {}
    try:
        return json.loads(fetch(PAGES_URL + "/ai.json"))
    except Exception:
        return {}


def age_hours(iso):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600
    except Exception:
        return 1e9


def ai_news(items, termine):
    """Top-Meldungen und Themenvorschläge."""
    order = {"maerkte": 0, "konjunktur": 0, "notenbanken": 0, "international": 1, "allgemein": 2}
    pool = sorted(items[:140], key=lambda i: order.get(i["category"], 1))[:110]
    listing = "\n".join(
        f'{it["id"]} | {it["category"]} | {it["source"]} | {it["title"]} | {it["subline"][:150]}' for it in pool)
    upcoming = "\n".join(
        f'{t["datum"]} | {t["unternehmen"]} ({t["region"]}){" | " + t["hinweis"] if t.get("hinweis") else ""}'
        f'{" | unbestätigt" if not t["bestaetigt"] else ""}'
        for t in termine[:40]) or "keine"
    today = today_berlin().strftime("%A, %d.%m.%Y")

    prompt = f"""Du unterstützt bei der Themenplanung für einen deutschsprachigen Instagram-Kanal über Geld
und Finanzen. Der Kanal ist edukativ und nachrichtenorientiert. Schwerpunkt: Wirtschaft, Finanzmärkte, Notenbanken,
Konjunkturdaten und Quartalszahlen. Allgemeine Nachrichten nur, wenn sie sehr bedeutend sind
oder klare Folgen für Wirtschaft und Märkte haben. Heute ist {today}.

AUFGABE 1: Wähle die bis zu {AI_PICKS} wichtigsten Meldungen. Fasse Meldungen zum selben Ereignis
zusammen (nur eine id). Je Auswahl: kurze deutsche Überschrift und eine deutsche Subline (ein Satz).

AUFGABE 2: Schlage {AI_SUGGESTIONS} Themen für Instagram-Posts vor, die sich heute oder in den
nächsten Tagen lohnen. Nutze dafür die Meldungen und die anstehenden Quartalszahlen. Mindestens ein
Vorschlag soll sich auf anstehende Quartalszahlen beziehen, wenn welche in den nächsten 7 Tagen anstehen.
Je Vorschlag:
- "thema": Stichwort, 2 bis 4 Wörter
- "ueberschrift": Post-Überschrift, höchstens 60 Zeichen, griffig aber sachlich, kein Clickbait
- "subline": ein Satz, höchstens 120 Zeichen
- "format": genau eines von "News-Kachel", "Erklär-Karussell", "Termin-Vorschau", "Zahl des Tages"
- "warum": ein Satz, warum das Thema für Anleger relevant ist
- "quellen": Liste der passenden Meldungs-ids (leer, wenn nur auf Terminen basiert)

REGELN: Nur Fakten aus den Meldungen und Terminen unten, nichts erfinden, keine Zahlen ergänzen.
Keine Anlageempfehlungen, keine Kursziele oder Prognosen, keine Wertung einzelner Aktien als
Kauf oder Verkauf. Neutral und erklärend formulieren. Alles auf Deutsch.

Antworte NUR mit JSON in dieser Form, ohne weiteren Text:
{{"top": [{{"id": "...", "titel": "...", "subline": "..."}}],
  "vorschlaege": [{{"thema": "...", "ueberschrift": "...", "subline": "...", "format": "...", "warum": "...", "quellen": ["..."]}}]}}

ANSTEHENDE QUARTALSZAHLEN (Datum | Unternehmen):
{upcoming}

MELDUNGEN (id | Kategorie | Quelle | Überschrift | Teaser):
{listing}"""
    res = extract_json(claude(AI_MODEL, prompt, 3000), "{")
    valid = {it["id"] for it in pool}
    top = [{"id": p["id"], "title": str(p.get("titel", "")).strip(), "subline": str(p.get("subline", "")).strip()}
           for p in res.get("top", []) if isinstance(p, dict) and p.get("id") in valid][:AI_PICKS]
    sugg = []
    for v in res.get("vorschlaege", [])[:AI_SUGGESTIONS + 1]:
        if not isinstance(v, dict) or not v.get("ueberschrift"):
            continue
        sugg.append({
            "topic": str(v.get("thema", "")).strip(),
            "headline": str(v.get("ueberschrift", "")).strip(),
            "subline": str(v.get("subline", "")).strip(),
            "format": str(v.get("format", "")).strip(),
            "why": str(v.get("warum", "")).strip(),
            "sources": [q for q in v.get("quellen", []) if q in valid][:4],
        })
    return top, sugg


def ai_termine():
    """Anstehende Quartalszahlen per Websuche recherchieren (einmal täglich)."""
    start = today_berlin()
    end = start + timedelta(days=TERMINE_DAYS)
    prompt = f"""Recherchiere, welche Unternehmen zwischen {start:%d.%m.%Y} und {end:%d.%m.%Y}
Quartalszahlen (oder Jahreszahlen) veröffentlichen. Relevant sind: alle DAX-Unternehmen, bekannte
MDAX-Werte sowie große, bekannte US-Unternehmen (z. B. große Tech-Konzerne, Großbanken, Einzelhandel,
Nvidia). Nutze verlässliche Terminkalender oder Investor-Relations-Seiten.

Antworte NUR mit einem JSON-Array, ohne weiteren Text:
[{{"datum": "JJJJ-MM-TT", "unternehmen": "...", "region": "DE" oder "US" oder "EU",
   "zeit": "z. B. 07:00, vorbörslich, nachbörslich oder leer", "bestaetigt": true oder false}}]
Setze "bestaetigt" nur auf true, wenn das Unternehmen den Termin selbst bestätigt hat oder mehrere
Quellen übereinstimmen. Nimm keine Termine auf, die du nicht in den Suchergebnissen gefunden hast."""
    text = claude(TERMINE_MODEL, prompt, 4000,
                  tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}], timeout=240)
    out = []
    for t in extract_json(text, "["):
        if isinstance(t, dict) and re.match(r"\d{4}-\d{2}-\d{2}$", str(t.get("datum", ""))) and t.get("unternehmen"):
            out.append({"datum": t["datum"], "unternehmen": str(t["unternehmen"]).strip(),
                        "region": str(t.get("region", "")).upper()[:2], "zeit": str(t.get("zeit", "") or ""),
                        "hinweis": "", "bestaetigt": bool(t.get("bestaetigt", False))})
    return out


def run_ai(items, manual_termine):
    """Gibt (ki_ergebnis, termine, hinweise) zurück. Ohne Schlüssel bleibt alles leer."""
    notes = []
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    prev = previous_ai()
    ai = {
        "enabled": has_key,
        "newsAt": prev.get("newsAt"), "top": prev.get("top"), "suggestions": prev.get("suggestions"),
        "termineAt": prev.get("termineAt"), "termineAuto": prev.get("termineAuto") or [],
    }
    if not has_key:
        return {"enabled": False}, merge_termine(manual_termine, []), notes

    if age_hours(ai["termineAt"] or "") >= TERMINE_INTERVAL_HOURS:
        try:
            ai["termineAuto"] = ai_termine()
            ai["termineAt"] = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            notes.append(f"Termin-Recherche fehlgeschlagen ({type(e).__name__}).")
    termine = merge_termine(manual_termine, ai["termineAuto"])

    ids = {it["id"]: it for it in items}
    stale_ids = any(p["id"] not in ids for p in (ai["top"] or []))
    if age_hours(ai["newsAt"] or "") >= AI_INTERVAL_HOURS or stale_ids or not ai["suggestions"]:
        try:
            ai["top"], ai["suggestions"] = ai_news(items, termine)
            ai["newsAt"] = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            notes.append(f"KI-Auswahl fehlgeschlagen ({type(e).__name__}), es werden die letzten Vorschläge gezeigt.")
    return ai, termine, notes


# ---------------------------------------------------------------- Main

def main():
    with open(FEEDS_FILE, encoding="utf-8") as f:
        feeds = json.load(f)["feeds"]

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(load_feed, feeds))

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MAX_AGE_HOURS)
    status, items, seen = [], [], set()

    for feed, its, err in results:
        kept = 0
        for it in its:
            if it["date"] and it["date"] < cutoff:
                continue
            if it["date"] and it["date"] > now + timedelta(hours=1):
                it["date"] = now
            key = it["link"] or it["title"].lower()
            tkey = re.sub(r"\W+", "", it["title"].lower())
            if key in seen or tkey in seen:
                continue
            seen.update({key, tkey})
            items.append(it)
            kept += 1
        status.append({"name": feed["name"], "ok": err is None, "count": kept, "error": err})

    items.sort(key=lambda i: i["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    # stabile ids (aus Link bzw. Titel), damit gespeicherte KI-Ergebnisse auch beim nächsten Lauf passen
    import hashlib
    for it in items:
        it["id"] = "n" + hashlib.sha1((it["link"] or it["title"]).encode()).hexdigest()[:10]
        it["_tokens"] = tokens(it["title"])

    topics = find_topics(items)
    ai, termine, notes = run_ai(items, load_manual_termine())

    out_items = [{
        "id": it["id"], "title": it["title"], "subline": it["subline"], "link": it["link"],
        "date": it["date"].isoformat() if it["date"] else None,
        "source": it["source"], "category": it["category"],
    } for it in items]

    data = {
        "generated": now.isoformat(),
        "items": out_items,
        "topics": topics,
        "ai": {k: ai.get(k) for k in ("enabled", "newsAt", "top", "suggestions", "termineAt")},
        "termine": termine,
        "notes": notes,
        "status": status,
    }

    with open(TEMPLATE_FILE, encoding="utf-8") as f:
        page = f.read()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = page.replace("/*__DATA__*/null", payload)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    with open(os.path.join(OUT_DIR, "ai.json"), "w", encoding="utf-8") as f:
        json.dump({k: ai.get(k) for k in ("newsAt", "top", "suggestions", "termineAt", "termineAuto")},
                  f, ensure_ascii=False)

    ok = sum(1 for s in status if s["ok"])
    print(f"{len(items)} Meldungen aus {ok}/{len(status)} Quellen, {len(topics)} Themen, "
          f"{len(termine)} Termine, {len(ai.get('suggestions') or [])} Themenvorschläge")
    for n in notes:
        print("  " + n, file=sys.stderr)
    for s in status:
        if not s["ok"]:
            print(f"  nicht erreichbar: {s['name']}: {s['error']}", file=sys.stderr)


if __name__ == "__main__":
    main()
