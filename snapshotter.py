#!/usr/bin/env python3
"""Снапшоттер расписания: раз в час сравнивает неделю всех активных групп
и при изменениях дёргает endpoints/diff бота (рассылка «⚠️ Изменения»).
Запускается кроном на VPS. Только stdlib.

Требует TGCLOUD_TOKEN в окружении (используется npx tgcloud run).
"""

import glob
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "http://127.0.0.1:8000"       # локальный asu-timetable
BOT_DIR = "/opt/rbasushedulebot"     # деплой tgcloud-бота
SNAP_DIR = "snapshots"               # рядом со скриптом
LOG = print

TOKEN_ENV = {"TGCLOUD_TOKEN": os.environ.get("TGCLOUD_TOKEN", "")}


def run_bot(module, payload):
    """npx tgcloud run <module> '<json>' — возвращает parsed json."""
    cmd = ["npx", "tgcloud", "run", module, json.dumps(payload, ensure_ascii=False)]
    p = subprocess.run(cmd, cwd=BOT_DIR, env={**os.environ, **TOKEN_ENV},
                       capture_output=True, text=True, timeout=300)
    out = p.stdout.strip()
    # последняя строка вида "< {json}" — берём её
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("< "):
            body = line[2:]
            try:
                return json.loads(body)
            except Exception:
                return body
    return None


def fetch_schedule(group_id, date):
    url = f"{BASE}/api/schedule?type=3&value={group_id}&date={date}&interval=2"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode())


def week_key(day):
    """компактная сигнатура дня для сравнения"""
    lessons = []
    for l in day.get("lessons", []):
        items = []
        for it in l.get("items", []):
            items.append({
                "s": it.get("subject"),
                "k": it.get("kind"),
                "r": it.get("rooms"),
                "t": it.get("teachers"),
            })
        lessons.append({"n": l.get("n"), "st": l.get("start"), "en": l.get("end"), "i": items})
    return lessons


def lesson_flat(l):
    it = (l.get("i") or [{}])[0]
    return {
        "n": l.get("n"),
        "start": l.get("st"),
        "end": l.get("en"),
        "subject": it.get("s") or "Занятие",
        "room": ", ".join(it.get("r") or []),
        "teacher": ", ".join(it.get("t") or []),
    }


def diff_days(old_days, new_days):
    """возвращает список изменений по дням"""
    changes = []
    old_map = {d["date"]: d for d in old_days}
    new_map = {d["date"]: d for d in new_days}

    for date, nd in new_map.items():
        od = old_map.get(date)
        old_lessons = week_key(od) if od else []
        new_lessons = week_key(nd)

        if old_lessons == new_lessons:
            continue

        old_by_n = {l["n"]: l for l in old_lessons}
        new_by_n = {l["n"]: l for l in new_lessons}
        removed, added, changed = [], [], []

        for n, l in old_by_n.items():
            if n not in new_by_n:
                removed.append(lesson_flat(l))
            elif new_by_n[n] != l:
                changed.append({"n": n, "before": lesson_flat(l), "after": lesson_flat(new_by_n[n])})
        for n, l in new_by_n.items():
            if n not in old_by_n:
                added.append(lesson_flat(l))

        if removed or added or changed:
            changes.append({
                "date": date,
                "weekday": nd.get("weekday", ""),
                "removed": removed,
                "added": added,
                "changed": changed,
            })
    return changes


def main():
    tz = timezone(timedelta(hours=7))
    now = datetime.now(tz)
    # неделя с понедельника текущей недели (или со следующего, если воскресенье)
    monday = now.date() - timedelta(days=now.weekday())
    if now.weekday() == 6:  # воскресенье — смотрим следующую неделю
        monday += timedelta(days=7)
    date = monday.strftime("%d.%m.%Y")

    os.makedirs(SNAP_DIR, exist_ok=True)
    snap_file = os.path.join(SNAP_DIR, f"week_{date}.json")
    prev = {}
    if os.path.exists(snap_file):
        with open(snap_file, encoding="utf-8") as f:
            prev = json.load(f)

    # активные группы из бота: строка "4873|1251С9-1;4328|1223в"
    act = run_bot("endpoints/activeGroups", {})
    if isinstance(act, str) and act.strip():
        groups = []
        for part in act.split(";"):
            if "|" not in part:
                continue
            gid, name = part.split("|", 1)
            groups.append({"groupId": gid.strip(), "groupName": name.strip()})
    else:
        groups = None
    if groups is None:
        LOG(f"!! не удалось получить активные группы: {act!r}")
        sys.exit(1)
    if not groups:
        LOG("активных групп нет — выходим")
        return

    LOG(f"групп: {len(groups)}, неделя с {date}, прошлый снапшот: {'есть' if prev else 'нет'}")

    current = {}
    for g in groups:
        gid = g["groupId"]
        try:
            days = fetch_schedule(gid, date).get("days", [])
        except Exception as e:
            LOG(f"  {g.get('groupName')}: fetch error {e}")
            continue
        current[gid] = days
        if gid in prev:
            ch = diff_days(prev[gid], days)
            if ch:
                LOG(f"  {g.get('groupName')}: {len(ch)} дней с изменениями")

    all_changes = []
    for g in groups:
        gid = g["groupId"]
        if gid not in prev or gid not in current:
            continue
        for day_ch in diff_days(prev[gid], current[gid]):
            all_changes.append({
                "groupId": gid,
                "groupName": g.get("groupName", gid),
                "date": day_ch["date"],
                "weekday": day_ch["weekday"],
                "removed": day_ch["removed"],
                "added": day_ch["added"],
                "changed": day_ch["changed"],
            })

    if all_changes and prev:
        LOG(f"изменений: {len(all_changes)} — рассылаю")
        res = run_bot("endpoints/diff", {"changes": all_changes})
        LOG(f"diff result: {res}")
    else:
        LOG("изменений нет")

    with open(snap_file, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False)

    # чистим старые снапшоты (оставляем текущую + прошлую неделю)
    snaps = sorted(glob.glob(os.path.join(SNAP_DIR, "week_*.json")))
    for old in snaps[:-2]:
        os.remove(old)


if __name__ == "__main__":
    main()
