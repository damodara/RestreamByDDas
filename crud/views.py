from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from crud.forms import DestinationForm, StreamForm
from crud.models import Rtmp, Stream


@login_required
def index(request):
    streams = Stream.objects.filter(owner=request.user)
    return render(request, "crud/index.html", {"streams": streams})


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
    return render(request, "crud/stream_detail.html", {"stream": stream})


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
        form = DestinationForm(request.POST)
        if form.is_valid():
            destination = form.save(commit=False)
            destination.stream = stream
            destination.save()
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
