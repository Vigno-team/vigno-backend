"""Endpoints de resultados acordados para E1C-17."""

from django.urls import path

from apps.clima import views
from apps.clima.correcciones_api import CorreccionesView, RevertirCorreccionView
from apps.clima.datos_frontend import ActualizacionView, DatosFrontendView, PrediccionFicticiaView
from apps.clima.fallas_rangos import FallasRangosView

app_name = "clima"

urlpatterns = [
    path("correcciones", CorreccionesView.as_view(), name="correcciones"),
    path(
        "correcciones/<int:pk>/revertir",
        RevertirCorreccionView.as_view(),
        name="revertir-correccion",
    ),
    path("datos", DatosFrontendView.as_view(), name="datos-frontend"),
    path("prediccion-ficticia", PrediccionFicticiaView.as_view(), name="prediccion-ficticia"),
    path("actualizacion", ActualizacionView.as_view(), name="actualizacion"),
    path("calidad/fallas", FallasRangosView.as_view(), name="fallas-calidad"),
    path("estaciones", views.EstacionesView.as_view(), name="estaciones"),
    path("temporadas", views.TemporadasView.as_view(), name="temporadas"),
    path("temporadas/<str:temporada>", views.FichaTemporadaView.as_view(), name="ficha-temporada"),
    path("rachas/<str:temporada>", views.RachasView.as_view(), name="rachas"),
]
