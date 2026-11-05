from django.urls import path

from apps.auditoria import views

app_name = "auditoria"

urlpatterns = [
    path("auditoria", views.AuditoriaView.as_view(), name="auditoria"),
]
