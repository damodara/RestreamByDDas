import hmac
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from crud.destination_logs import MAX_LINES, read_destination_log
from crud.destination_presets import DESTINATION_PRESETS
from crud.destination_test import test_push
from crud.emails import send_push_error_email
from crud.forms import DestinationForm, StreamChatForm, StreamForm
from crud.models import ChatMessage, Rtmp, Stream, generate_stream_key
from crud.nginx_control import restart_stream
from crud.nginx_stat import fetch_live_stream_keys, fetch_stream_stats
from crud.server_load import get_server_load


def _hook_authorized(request):
    secret = request.GET.get("secret", "")
    return bool(settings.RTMP_HOOK_SECRET) and hmac.compare_digest(
        secret, settings.RTMP_HOOK_SECRET
    )


def _stream_live_status(stream, live_keys):
    """Общая логика между index (первая загрузка) и index_live_json
    (поллинг) — держим в одном месте по тому же принципу, что и
    _stream_stats выше. push_error — та же staleness-логика, что и у
    push_status в _stream_stats: считается только пока сам поток live,
    иначе старая "ошибка" от прошлого сеанса висела бы бейджем на главной
    даже после того, как проблемную дестинацию выключили или стрим давно
    закончился."""
    live = stream.stream_key in live_keys
    push_error = live and any(
        d.enabled and d.push_status == Rtmp.PushStatus.ERROR
        for d in stream.destinations.all()
    )
    return {"live": live, "push_error": push_error}


@login_required
def index(request):
    streams = list(
        Stream.objects.filter(owner=request.user).prefetch_related("destinations")
    )
    live_keys = fetch_live_stream_keys()
    # None (не тот же случай, что "пустое множество" — /stat может быть
    # просто недоступен, а не "все точки приёма офлайн") здесь уже не нужен
    # шаблону: bool(None) == False, а .stream_key in set() тоже всегда
    # False, так что "не в эфире"/"без ошибок" — безопасный дефолт и для
    # "недоступно", и для "правда офлайн". Отдельный stats_available нужен
    # только чтобы вообще решить, показывать бейдж или нет (см.
    # index_live_json ниже — та же логика).
    for stream in streams:
        stream.live_status = _stream_live_status(stream, live_keys or set())
    return render(
        request,
        "crud/index.html",
        {
            "streams": streams,
            "server_load": get_server_load(),
            "stats_available": live_keys is not None,
        },
    )


@login_required
@require_GET
def index_live_json(request):
    live_keys = fetch_live_stream_keys()
    streams = Stream.objects.filter(owner=request.user).prefetch_related("destinations")
    if live_keys is None:
        return JsonResponse({"available": False, "streams": {}})
    return JsonResponse(
        {
            "available": True,
            "streams": {str(s.id): _stream_live_status(s, live_keys) for s in streams},
        }
    )


@login_required
def stream_create(request):
    if request.method == "POST":
        form = StreamForm(request.POST)
        if form.is_valid():
            stream = form.save(commit=False)
            stream.owner = request.user
            stream.save()
            return redirect("crud:stream_detail", stream_id=stream.pk)
    else:
        form = StreamForm()
    return render(request, "crud/stream_form.html", {"form": form})


def _stream_stats(stream):
    """Общая логика между stream_detail (HTML) и stream_stats_json — держим
    в одном месте, чтобы обновление на лету (JS-поллинг) не могло разойтись
    с тем, что рендерится при обычной загрузке страницы."""
    stats = fetch_stream_stats(stream.stream_key)
    if stats and stats.get("live"):
        stats["uptime_display"] = (
            f"{stats['uptime_seconds'] // 60}:{stats['uptime_seconds'] % 60:02d}"
        )
    live = bool(stats and stats.get("live"))
    destinations = [
        {
            "id": d.id,
            # Тот же staleness-guard, что и в шаблоне: статус пуша не
            # показываем, если по /stat сам стрим сейчас не live, и не
            # показываем для выключенной тумблером дестинации — иначе
            # старый push_status (например "error" от предыдущего сеанса,
            # из-за которого дестинацию и выключили) продолжал бы висеть
            # бейджем, хотя в неё сейчас вообще ничего не льётся.
            "push_status": d.push_status if (live and d.enabled) else None,
        }
        for d in stream.destinations.all()
    ]
    return stats, destinations


@login_required
def stream_detail(request, stream_id):
    stream = get_object_or_404(Stream, pk=stream_id, owner=request.user)
    stats, _ = _stream_stats(stream)
    return render(
        request,
        "crud/stream_detail.html",
        {"stream": stream, "stats": stats, "server_load": get_server_load()},
    )


@login_required
@require_GET
def server_load_json(request):
    return JsonResponse(get_server_load())


@login_required
@require_GET
def stream_stats_json(request, stream_id):
    stream = get_object_or_404(Stream, pk=stream_id, owner=request.user)
    stats, destinations = _stream_stats(stream)
    return JsonResponse({"stats": stats, "destinations": destinations})


@login_required
@require_GET
def stream_chat_json(request, stream_id):
    stream = get_object_or_404(Stream, pk=stream_id, owner=request.user)
    chat_enabled = bool(stream.youtube_chat_video_id)
    if not chat_enabled:
        # Источник отключён — не отдаём сообщения, даже если старые строки
        # почему-то остались в БД (например, отключили через "Сохранить"
        # с пустым полем, а не через "Сбросить" — тот сразу чистит
        # историю, но полагаться на то, что чистка произошла именно
        # так/именно тогда, не стоит; эндпоинт сам не должен путать
        # "чат не подключён" с "чат подключён, но сообщений пока нет").
        return JsonResponse({"messages": [], "chat_enabled": False})

    after_id = request.GET.get("after_id")
    qs = stream.chat_messages.all()
    if after_id:
        # Инкрементальный поллинг — только новые сообщения с прошлого раза.
        messages_qs = qs.filter(pk__gt=after_id)
    else:
        # Первая загрузка страницы — последние 50, в хронологическом порядке.
        messages_qs = reversed(qs.order_by("-posted_at")[:50])
    messages = [
        {
            "id": message.id,
            "author_name": message.author_name,
            "text": message.text,
            "posted_at": message.posted_at.isoformat(),
        }
        for message in messages_qs
    ]
    return JsonResponse({"messages": messages, "chat_enabled": True})


@login_required
@require_POST
def stream_chat_settings(request, stream_id):
    stream = get_object_or_404(Stream, pk=stream_id, owner=request.user)
    form = StreamChatForm(request.POST, instance=stream)
    if form.is_valid():
        form.save()
        if not stream.youtube_chat_video_id:
            # То же самое, что и явный "Сбросить" — источник отключили,
            # какой бы кнопкой это ни было сделано. Иначе сообщения от
            # прошлой трансляции просто остаются в БД до следующего
            # подключения нового видео и путаются с новыми.
            stream.chat_messages.all().delete()
        messages.success(request, "Настройки чата сохранены.")
    else:
        messages.error(request, "Не удалось сохранить — проверьте ссылку/ID.")
    return redirect("crud:stream_detail", stream_id=stream.pk)


@login_required
@require_POST
def stream_chat_reset(request, stream_id):
    stream = get_object_or_404(Stream, pk=stream_id, owner=request.user)
    stream.youtube_chat_video_id = ""
    stream.save(update_fields=["youtube_chat_video_id"])
    # Иначе при следующем подключении чата к новому видео старые
    # сообщения от прошлой трансляции остались бы висеть вперемешку с
    # новыми — сброс должен быть чистым, не только отключением источника.
    stream.chat_messages.all().delete()
    messages.success(request, "Чат отключён, история сообщений очищена.")
    return redirect("crud:stream_detail", stream_id=stream.pk)


@login_required
@require_POST
def stream_restart(request, stream_id):
    stream = get_object_or_404(Stream, pk=stream_id, owner=request.user)
    if restart_stream(stream.stream_key):
        messages.success(request, "Сигнал на перезапуск отправлен.")
    else:
        messages.error(request, "Не удалось перезапустить — инфраструктура недоступна.")
    return redirect("crud:stream_detail", stream_id=stream.pk)


@login_required
@require_POST
def stream_regenerate_key(request, stream_id):
    stream = get_object_or_404(Stream, pk=stream_id, owner=request.user)
    old_key = stream.stream_key
    stream.stream_key = generate_stream_key()
    stream.save(update_fields=["stream_key"])
    # Сам ключ в БД мы уже сменили, но действующий паблишер (если он есть)
    # nginx всё ещё держит под СТАРЫМ ключом — restart_stream(stream_key)
    # дропает по имени потока, так что дропать нужно именно старый key,
    # иначе живой стрим продолжит литься по уже недействительному ключу до
    # тех пор, пока клиент сам не отключится (тот же принцип, что и у
    # stream_delete ниже).
    restart_stream(old_key)
    messages.success(
        request, "Ключ обновлён. Старый ключ больше не работает для публикации."
    )
    return redirect("crud:stream_detail", stream_id=stream.pk)


@login_required
def stream_delete(request, stream_id):
    stream = get_object_or_404(Stream, pk=stream_id, owner=request.user)
    if request.method == "POST":
        stream_key = stream.stream_key
        stream.delete()
        # Удаление строки в БД никак не сигналит nginx — уже принятый
        # паблишер продолжил бы литься на все дестинации до тех пор, пока
        # стример сам не отключится (подтверждено живым тестом). Сбрасываем
        # текущего паблишера тем же механизмом, что и "Перезапустить
        # трансляцию" — раз точки приёма больше нет, переподключиться
        # (и снова пройти on_publish_hook) уже не получится.
        restart_stream(stream_key)
        return redirect("crud:index")
    return render(
        request,
        "crud/confirm_delete.html",
        {"object": stream, "object_label": stream.name},
    )


@login_required
def destination_create(request, stream_id):
    stream = get_object_or_404(Stream, pk=stream_id, owner=request.user)
    if request.method == "POST":
        # Блокируем строку Stream на время проверки+сохранения — иначе два
        # параллельных сабмита с одинаковым RTMP-ключом могут оба пройти
        # проверку уникальности в DestinationForm (она теперь только на
        # уровне приложения, т.к. поле зашифровано и не детерминировано,
        # DB unique_together по нему больше не работает).
        with transaction.atomic():
            Stream.objects.select_for_update().get(pk=stream.pk)
            form = DestinationForm(request.POST, instance=Rtmp(stream=stream))
            if form.is_valid():
                form.save()
                return redirect("crud:stream_detail", stream_id=stream.pk)
    else:
        form = DestinationForm()
    return render(
        request,
        "crud/destination_form.html",
        {"form": form, "stream": stream, "presets": DESTINATION_PRESETS},
    )


@login_required
def destination_update(request, destination_id):
    destination = get_object_or_404(Rtmp, pk=destination_id, stream__owner=request.user)
    if request.method == "POST":
        with transaction.atomic():
            Stream.objects.select_for_update().get(pk=destination.stream_id)
            form = DestinationForm(request.POST, instance=destination)
            if form.is_valid():
                form.save()
                return redirect("crud:stream_detail", stream_id=destination.stream_id)
    else:
        form = DestinationForm(instance=destination)
    return render(
        request,
        "crud/destination_form.html",
        {"form": form, "stream": destination.stream, "presets": DESTINATION_PRESETS},
    )


@login_required
def destination_delete(request, destination_id):
    destination = get_object_or_404(Rtmp, pk=destination_id, stream__owner=request.user)
    if request.method == "POST":
        stream_id = destination.stream_id
        destination.delete()
        return redirect("crud:stream_detail", stream_id=stream_id)
    return render(
        request,
        "crud/confirm_delete.html",
        {"object": destination, "object_label": destination.socialmedia_name},
    )


@login_required
@require_POST
def destination_toggle(request, destination_id):
    destination = get_object_or_404(Rtmp, pk=destination_id, stream__owner=request.user)
    destination.enabled = not destination.enabled
    destination.save(update_fields=["enabled"])
    if destination.enabled:
        messages.success(request, f"«{destination.socialmedia_name}» включена.")
    else:
        messages.success(request, f"«{destination.socialmedia_name}» выключена.")
    return redirect("crud:stream_detail", stream_id=destination.stream_id)


@login_required
@require_POST
def destination_test_push(request, destination_id):
    destination = get_object_or_404(Rtmp, pk=destination_id, stream__owner=request.user)
    success, detail = test_push(destination.push_url)
    if success:
        messages.success(request, f"«{destination.socialmedia_name}»: {detail}")
    else:
        messages.error(request, f"«{destination.socialmedia_name}»: {detail}")
    return redirect("crud:stream_detail", stream_id=destination.stream_id)


@login_required
def destination_log(request, destination_id):
    destination = get_object_or_404(Rtmp, pk=destination_id, stream__owner=request.user)
    log_text = read_destination_log(destination.stream.stream_key, destination.id)
    return render(
        request,
        "crud/destination_log.html",
        {"destination": destination, "log_text": log_text, "max_lines": MAX_LINES},
    )


@login_required
@require_GET
def destination_log_json(request, destination_id):
    destination = get_object_or_404(Rtmp, pk=destination_id, stream__owner=request.user)
    log_text = read_destination_log(destination.stream.stream_key, destination.id)
    return JsonResponse({"log_text": log_text})


@csrf_exempt
@require_POST
def on_publish_hook(request):
    if not _hook_authorized(request):
        return HttpResponseForbidden()
    stream_key = request.POST.get("name", "")
    if Stream.objects.filter(stream_key=stream_key).exists():
        return HttpResponse(status=200)
    return HttpResponseForbidden()


@require_GET
def stream_destinations_hook(request, stream_key):
    if not _hook_authorized(request):
        return HttpResponseForbidden()
    stream = Stream.objects.filter(stream_key=stream_key).first()
    if stream is None:
        return JsonResponse([], safe=False)
    destinations = [
        {"id": destination.id, "push_url": destination.push_url}
        for destination in stream.destinations.filter(enabled=True)
    ]
    return JsonResponse(destinations, safe=False)


@csrf_exempt
@require_POST
def destination_status_hook(request):
    if not _hook_authorized(request):
        return HttpResponseForbidden()
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseForbidden()
    status = payload.get("status")
    if status not in Rtmp.PushStatus.values:
        return HttpResponseForbidden()
    # Достаём объект (а не сразу .update()), чтобы поймать именно переход
    # В ошибку, а не каждый повторный отчёт об уже известной ошибке —
    # иначе при "зависшем" реконнекте пользователь получал бы письмо на
    # каждый повторный статус-репорт push.sh вместо одного на инцидент.
    # select_related на владельца — он же нужен для email-уведомления,
    # незачем делать отдельный запрос.
    destination = (
        Rtmp.objects.select_related("stream__owner")
        .filter(pk=payload.get("destination_id"))
        .first()
    )
    if destination is None:
        # Дестинацию удалили прямо во время публикации — тихий no-op, а не
        # ошибка: push.sh не в состоянии ничего сделать с ответом хука,
        # это fire-and-forget.
        return HttpResponse(status=200)
    was_error = destination.push_status == Rtmp.PushStatus.ERROR
    Rtmp.objects.filter(pk=destination.pk).update(
        push_status=status, push_status_at=timezone.now()
    )
    if (
        status == Rtmp.PushStatus.ERROR
        and not was_error
        and destination.stream.owner.notify_on_push_error
    ):
        send_push_error_email(destination)
    return HttpResponse(status=200)


@csrf_exempt
@require_POST
def srt_auth_hook(request):
    if not _hook_authorized(request):
        return HttpResponseForbidden()
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseForbidden()
    if payload.get("action") != "publish":
        return HttpResponse(status=200)
    stream_key = payload.get("path", "")
    if Stream.objects.filter(stream_key=stream_key).exists():
        return HttpResponse(status=200)
    return HttpResponseForbidden()
