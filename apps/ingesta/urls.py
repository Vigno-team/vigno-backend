"""Carga de Excel por API (E1C-66)."""

from django.urls import path

from apps.ingesta import views

app_name = "ingesta"

urlpatterns = [
    path("cargas", views.CargasView.as_view(), name="cargas"),
    path("cargas/<int:pk>", views.CargaView.as_view(), name="carga"),
]
