from django.http import HttpResponse
from django.shortcuts import render
from django.template import loader

from crud.models import Rtmp

# получение данных из бд
def index(request):
    rtmp = Rtmp.objects.all()
    return render(request, "crud/index.html", {"rtmps": rtmp})


def create(request):
    return HttpResponse("create page")


def read(request, rtmp_id):
        template = loader.get_template("crud/index.html")
        context = {"rtmp_id": rtmp_id}
        return render(request, template, context)


def update(request, rtmp_id):
    return HttpResponse(f"update page {rtmp_id}")


def delete(request):
    return HttpResponse("delete page")
