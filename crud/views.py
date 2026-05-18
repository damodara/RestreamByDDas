from django.http import HttpResponse


def create(request):
    return HttpResponse("create page")


def read(request):
    return HttpResponse("read page")


def update(request):
    return HttpResponse("update page")


def delete(request):
    return HttpResponse("delete page")
