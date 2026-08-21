import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from crud.forms import DestinationForm, StreamForm
from crud.models import Rtmp, Stream
from crud.nginx_control import restart_stream
from crud.nginx_stat import fetch_stream_stats
from crud.server_load import get_server_load


def _hook_authorized(request):
    secret = request.GET.get("secret", "")
    return bool(settings.RTMP_HOOK_SECRET) and secret == settings.RTMP_HOOK_SECRET


@login_required
def index(request):
    streams = Stream.objects.filter(owner=request.user)
    return render(
        request,
        "crud/index.html",
        {"streams": streams, "server_load": get_server_load()},
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


@login_required
def stream_detail(request, stream_id):
    stream = get_object_or_404(Stream, pk=stream_id, owner=request.user)
    stats = fetch_stream_stats(stream.stream_key)
    if stats and stats.get("live"):
        stats["uptime_display"] = (
            f"{stats['uptime_seconds'] // 60}:{stats['uptime_seconds'] % 60:02d}"
        )
    return render(
        request, "crud/stream_detail.html", {"stream": stream, "stats": stats}
    )


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
def stream_delete(request, stream_id):
    stream = get_object_or_404(Stream, pk=stream_id, owner=request.user)
    if request.method == "POST":
        stream.delete()
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
        form = DestinationForm(request.POST, instance=Rtmp(stream=stream))
        if form.is_valid():
            form.save()
            return redirect("crud:stream_detail", stream_id=stream.pk)
    else:
        form = DestinationForm()
    return render(
        request, "crud/destination_form.html", {"form": form, "stream": stream}
    )


@login_required
def destination_update(request, destination_id):
    destination = get_object_or_404(Rtmp, pk=destination_id, stream__owner=request.user)
    if request.method == "POST":
        form = DestinationForm(request.POST, instance=destination)
        if form.is_valid():
            form.save()
            return redirect("crud:stream_detail", stream_id=destination.stream_id)
    else:
        form = DestinationForm(instance=destination)
    return render(
        request,
        "crud/destination_form.html",
        {"form": form, "stream": destination.stream},
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
        {"push_url": destination.push_url} for destination in stream.destinations.all()
    ]
    return JsonResponse(destinations, safe=False)


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
