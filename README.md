# asu-rub-api

Неофициальное **JSON API расписания** [Рубцовского института (филиала) АлтГУ](https://rb.asu.ru) — лёгкий прокси-парсер на чистом Python (только stdlib, ноль зависимостей).

Забирает html с `rb.asu.ru`, парсит и отдаёт нормальный JSON. Заодно обходит блокировку запросов из облачной инфраструктуры (Telegram Serverless и т.п.).

[![api](https://img.shields.io/website?url=https%3A%2F%2Fasu.rub22.ru%2Fapi%2Fhealth&label=api&up_message=online&down_message=offline)](https://asu.rub22.ru/api/health)

**Живой инстанс:** https://asu.rub22.ru

## API

### Статус

```
GET /api/health
```

Проверяет доступность апстрима: `{"status": "ok", "groups": 165, ...}` — 200 или 503. Бейдж в шапке README тянется отсюда.

### Список групп / преподавателей / аудиторий

```
GET /api/selectors?kind=groups
```

| kind | что возвращает |
|------|----------------|
| `groups` | группы (165+) |
| `teachers` | преподаватели |
| `rooms` | аудитории |
| `chairs` | кафедры (пусто у них) |

Ответ:

```json
{
  "items": [
    { "id": "4507", "name": "1235", "title": "" },
    { "id": "4508", "name": "1236", "title": "" }
  ],
  "fetched_at": 1762700000
}
```

### Расписание

```
GET /api/schedule?type=3&value=4507&date=09.11.2026&interval=2
```

| параметр | значения |
|----------|----------|
| `type` | `1` — преподаватель · `2` — аудитория · `3` — группа |
| `value` | id из `/api/selectors` |
| `date` | `dd.mm.yyyy` — точка отсчёта |
| `interval` | `1` — день · `2` — неделя · `3` — месяц |

Ответ:

```json
{
  "days": [
    {
      "weekday": "Понедельник",
      "date": "09.11.2026",
      "lessons": [
        {
          "n": 3,
          "start": "11:20",
          "end": "12:50",
          "items": [
            {
              "subject": "Корпоративные информационные системы",
              "kind": "Лабораторное занятие №10",
              "rooms": ["304"],
              "groups": ["1235", "1245и"],
              "teachers": ["Краснослободцева Ирина Сергеевна"],
              "degree": "Старший преподаватель"
            }
          ],
          "equipment": ["ПК", "Телевизор", "Интернет подключение"]
        }
      ]
    }
  ]
}
```

Слоты звонков: `1` 08:00–09:30 · `2` 09:40–11:10 · `3` 11:20–12:50 · `4` 13:20–14:50 · `5` 15:00–16:30 · `6` 16:40–18:10 · `7` 18:20–19:40 · `8` 19:50–21:10

## Запуск

```bash
python3 app.py   # → http://localhost:8000
```

Никаких зависимостей — только стандартная библиотека Python 3. В комплекте веб-морда (`static/index.html`) на том же порту.

## Исходник данных

Всё тянется с официального `rb.asu.ru`:

```
POST /timetable/helperselect   body: type=3
POST /timetable/get            body: sday=09.11.2026&time_interval=2&type=3&value=4507&title=&fname=&student=0
```

Проект не связан с АлтГУ. Только публичные данные расписания.

## License

MIT

## Детектор изменений расписания

`snapshotter.py` — кроном раз в час:
1. берёт активные группы бота (`endpoints/activeGroups`)
2. тянет неделю через локальный api
3. сравнивает со снапшотом (`snapshots/week_DD.MM.YYYY.json`)
4. при изменениях дёргает `endpoints/diff` — юзеры группы получают «⚠️ Изменения в расписании»

Крон (VPS):
```cron
15 * * * * cd /opt/asu-timetable && TGCLOUD_TOKEN=... /usr/bin/python3 snapshotter.py >> /var/log/rbasu-snap.log 2>&1
```
