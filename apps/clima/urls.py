"""Endpoints de resultados acordados para E1C-17."""

from django.urls import path

from apps.clima import views
from apps.clima.fallas_rangos import FallasRangosView

app_name = "clima"

urlpatterns = [
    path("calidad/fallas", FallasRangosView.as_view(), name="fallas-calidad"),
    path("estaciones", views.EstacionesView.as_view(), name="estaciones"),
    path("temporadas", views.TemporadasView.as_view(), name="temporadas"),
    path("temporadas/<str:temporada>", views.FichaTemporadaView.as_view(), name="ficha-temporada"),
    path("rachas/<str:temporada>", views.RachasView.as_view(), name="rachas"),
]
