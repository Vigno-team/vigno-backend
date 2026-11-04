"""Login con correo y tokens JWT (E1C-64)."""

from django.urls import path

from apps.cuentas import views

app_name = "cuentas"

urlpatterns = [
    path("auth/token", views.LoginView.as_view(), name="token"),
    path("auth/refresh", views.RefrescoView.as_view(), name="refresh"),
    path("auth/logout", views.CerrarSesionView.as_view(), name="logout"),
    path("auth/yo", views.YoView.as_view(), name="yo"),
    path("auth/cambiar-clave", views.CambiarClaveView.as_view(), name="cambiar-clave"),
]
