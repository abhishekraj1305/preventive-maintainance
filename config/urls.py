from django.http import HttpResponse
from django.urls import path, include
from django.db import connection


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return HttpResponse("unavailable", status=503)
    return HttpResponse("ok")


urlpatterns = [path("health/", health), path("", include("maintenance.urls"))]
