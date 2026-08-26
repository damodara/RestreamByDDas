# Только площадки, чей публичный RTMP ingest-адрес стабилен и
# задокументирован годами (в т.ч. зашит как встроенный пресет в OBS) — тот
# же принцип осторожности, что и у решения не подключать VK нигде в проекте
# (см. CLAUDE.md): не подставляем пользователю адрес, который не можем
# подтвердить напрямую, а не переписываем откуда-то по памяти. Список сугубо
# для автозаполнения формы destination_form.html — ничего не хранится и не
# проверяется этими значениями на бэкенде.
DESTINATION_PRESETS = [
    {"name": "YouTube", "rtmp_link": "rtmp://a.rtmp.youtube.com/live2"},
    {"name": "Twitch", "rtmp_link": "rtmp://live.twitch.tv/app"},
    {"name": "Facebook Live", "rtmp_link": "rtmps://live-api-s.facebook.com:443/rtmp"},
]
