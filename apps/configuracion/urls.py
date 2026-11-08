from django.urls import path

from apps.configuracion import views

app_name = "configuracion"

urlpatterns = [
    path("configuracion", views.ConfiguracionView.as_view(), name="configuracion"),
    path("configuracion/logo", views.LogoView.as_view(), name="logo"),
]
