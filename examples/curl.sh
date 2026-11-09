# примеры использования API

# все группы
curl "https://asu.rub22.ru/api/selectors?kind=groups"

# преподаватели
curl "https://asu.rub22.ru/api/selectors?kind=teachers"

# расписание группы 1235 на неделю
curl "https://asu.rub22.ru/api/schedule?type=3&value=4507&date=09.11.2026&interval=2"

# расписание на один день
curl "https://asu.rub22.ru/api/schedule?type=3&value=4507&date=10.11.2026&interval=1"

# расписание на месяц
curl "https://asu.rub22.ru/api/schedule?type=3&value=4507&date=09.11.2026&interval=3"

# расписание преподавателя (uuid из selectors?kind=teachers)
curl "https://asu.rub22.ru/api/schedule?type=1&value=92f7341b-ade5-11dc-8c11-0016e652202c&date=09.11.2026&interval=2"

# занятость аудитории 304
# value — id аудитории из selectors?kind=rooms
curl "https://asu.rub22.ru/api/schedule?type=2&value=<room_id>&date=09.11.2026&interval=2"
