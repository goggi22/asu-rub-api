#!/usr/bin/env python3
"""Прокси + парсер расписания rb.asu.ru. Только stdlib."""

import json
import re
import time
import urllib.parse
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler

UPSTREAM = "https://rb.asu.ru"
CACHE_TTL = 6 * 3600
_selector_cache = {}  # type -> (timestamp, payload)


def upstream_post(path, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        UPSTREAM + path,
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


LINK_RE = re.compile(r'<a[^>]*submitform\(\'(\d)\',\'([^\']+)\'\)[^>]*>\s*([^<]*?)\s*</a>')
P_RE = re.compile(r"<p>(.*?)</p>", re.S)
KIND_RE = re.compile(r"\(([^()]*(?:занятие|лекция|практика|семинар|экзамен|зачёт|зачет|консультация)[^()]*)\)\s*$", re.I)
DAY_SPLIT_RE = re.compile(r'<tr class="Day">', re.S)
TH_RE = re.compile(r"<th>(.*?)</th>", re.S)
TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
NUM_RE = re.compile(r"<td>\s*(\d+)\s*</td>")
TIME_RE = re.compile(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")
EQUIP_RE = re.compile(r"<i class='fa[^']*' title='([^']*)'")
TAG_RE = re.compile(r"<[^>]+>")


def cell_text(fragment):
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", fragment)).strip(" ;")


def parse_lesson(p_html):
    first_tag = re.search(r"<[a-br]", p_html)
    head = p_html[: first_tag.start()] if first_tag else p_html
    head = re.sub(r"\s+", " ", TAG_RE.sub(" ", head)).strip(" ;,")

    kind = ""
    m = KIND_RE.search(head)
    if m:
        kind = m.group(1).strip()
        head = head[: m.start()].strip()

    rooms, groups, teachers = [], [], []
    degree = ""
    for t, _id, label in LINK_RE.findall(p_html):
        if t == "2":
            rooms.append(label)
        elif t == "3":
            groups.append(label)
        elif t == "1":
            teachers.append(label)

    before_teacher = re.split(r"submitform\('1'", p_html)[0]
    degree = cell_text(before_teacher.split("<br")[-1].split("<a ")[0]).rstrip(",")
    degree = re.sub(r"^[\s/>]+", "", degree).strip(" ;,").strip()
    if degree in (" ".join(groups), ""):
        degree = ""

    return {
        "subject": head,
        "kind": kind,
        "rooms": rooms,
        "groups": groups,
        "teachers": teachers,
        "degree": degree,
    }


def parse_timetable(html):
    days = []
    chunks = DAY_SPLIT_RE.split(html)[1:]
    for chunk in chunks:
        day_title = None
        for th in TH_RE.findall(chunk):
            text = re.sub(r"\s+", " ", TAG_RE.sub("", th)).strip()
            if re.match(r"(\S+)\s+(\d{2}\.\d{2}\.\d{4})", text):
                day_title = text
                break
        if not day_title:
            continue
        m = re.match(r"(\S+)\s+(\d{2}\.\d{2}\.\d{4})", day_title)
        day = {"weekday": m.group(1), "date": m.group(2), "lessons": {}}
        for row in TR_RE.findall(chunk):
            n = NUM_RE.search(row)
            tm = TIME_RE.search(row)
            if not n or not tm:
                continue
            content_m = re.search(r"название пары[^>]*-->(.*?)(?:<!--|$)", row, re.S)
            content = content_m.group(1) if content_m else row
            equip_m = re.search(r"hidden-xs[^>]*>(.*?)(?:<!--|$)", row, re.S)
            equipment = [t.strip() for t in EQUIP_RE.findall(equip_m.group(1))] if equip_m else []
            lessons = [parse_lesson(p) for p in P_RE.findall(content)]
            lessons = [l for l in lessons if l["subject"] or l["rooms"]]
            if lessons:
                day["lessons"][int(n.group(1))] = {
                    "start": tm.group(1),
                    "end": tm.group(2),
                    "items": lessons,
                    "equipment": equipment,
                }
        day["lessons"] = [{"n": k, **v} for k, v in sorted(day["lessons"].items())]
        days.append(day)
    return days


SELECTOR_TYPES = {"teachers": 1, "rooms": 2, "groups": 3, "chairs": 4}


def get_selectors(kind):
    now = time.time()
    cached = _selector_cache.get(kind)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]
    html = upstream_post("/timetable/helperselect", {"type": SELECTOR_TYPES[kind]})
    items = []
    for m in re.finditer(
        r'<option value="([^"]+)"[^>]*fname="([^"]*)"(?:\s+title="([^"]*)")?[^>]*>(.*?)</option>',
        html,
        re.S,
    ):
        label = re.sub(r"\s+", " ", TAG_RE.sub("", m.group(4))).strip()
        items.append({"id": m.group(1), "name": m.group(2) or label, "title": (m.group(3) or "").strip()})
    payload = {"items": items, "fetched_at": int(now)}
    _selector_cache[kind] = (now, payload)
    return payload


def get_schedule(itype, value, date, interval):
    html = upstream_post(
        "/timetable/get",
        {
            "sday": date,
            "time_interval": interval,
            "type": itype,
            "value": value,
            "title": "",
            "fname": "",
            "student": 0,
        },
    )
    return {"days": parse_timetable(html)}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory="static", **kw)

    def log_message(self, fmt, *args):
        print("[%s] %s" % (time.strftime("%H:%M:%S"), fmt % args))

    def json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        # shields.io и прочие мониторы проверяют HEAD-запросом
        if urllib.parse.urlparse(self.path).path == "/api/health":
            ok, detail = True, "ok"
            try:
                probe = get_selectors("groups")
                if not probe.get("items"):
                    ok, detail = False, "empty groups"
            except Exception as e:
                ok, detail = False, str(e)[:200]
            self.send_response(200 if ok else 503)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", "0")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return
        super().do_HEAD()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/api/health":
            ok, detail = True, "ok"
            try:
                probe = get_selectors("groups")
                if not probe.get("items"):
                    ok, detail = False, "empty groups"
            except Exception as e:
                ok, detail = False, str(e)[:200]
            return self.json(
                {
                    "status": "ok" if ok else "degraded",
                    "detail": detail,
                    "upstream": UPSTREAM,
                    "groups": len(_selector_cache.get("groups", (0, {}))[1].get("items", [])),
                    "time": int(time.time()),
                },
                200 if ok else 503,
            )

        if parsed.path == "/api/selectors":
            kind = (qs.get("kind") or ["groups"])[0]
            if kind not in SELECTOR_TYPES:
                return self.json({"error": "bad kind"}, 400)
            try:
                return self.json(get_selectors(kind))
            except Exception as e:
                return self.json({"error": str(e)}, 502)

        if parsed.path == "/api/schedule":
            itype = (qs.get("type") or ["3"])[0]
            value = (qs.get("value") or [""])[0]
            date = (qs.get("date") or [""])[0]
            interval = (qs.get("interval") or ["2"])[0]
            if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", date):
                return self.json({"error": "date must be dd.mm.yyyy"}, 400)
            if not value:
                return self.json({"error": "value required"}, 400)
            try:
                return self.json(get_schedule(itype, value, date, interval))
            except Exception as e:
                return self.json({"error": str(e)}, 502)

        return super().do_GET()


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8000), Handler)
    print("→ http://localhost:8000")
    server.serve_forever()
