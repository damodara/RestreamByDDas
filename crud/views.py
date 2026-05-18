from django.http import HttpResponse


def create(request):
    return HttpResponse("create page")


def read(request):
    return HttpResponse("read page")


def update(request, rtmp_id):
    return HttpResponse(f"update page {rtmp_id}")


def delete(request):
    return HttpResponse("delete page")
