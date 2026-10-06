"""Endpoints de resultados acordados para E1C-17."""

from django.urls import path

from apps.clima import views

app_name = "clima"

urlpatterns = [
    path("estaciones", views.EstacionesView.as_view(), name="estaciones"),
    path("temporadas", views.TemporadasView.as_view(), name="temporadas"),
    path("temporadas/<str:temporada>", views.FichaTemporadaView.as_view(), name="ficha-temporada"),
    path("rachas/<str:temporada>", views.RachasView.as_view(), name="rachas"),
]
