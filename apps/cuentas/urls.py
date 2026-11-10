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
    path("auth/recuperacion", views.RecuperacionView.as_view(), name="recuperacion"),
    path("auth/recuperar-clave", views.RecuperarClaveView.as_view(), name="recuperar-clave"),
    path(
        "auth/restablecer-clave",
        views.RestablecerClavePorCorreoView.as_view(),
        name="restablecer-clave",
    ),
    path("usuarios", views.UsuariosView.as_view(), name="usuarios"),
    path("usuarios/<int:pk>", views.UsuarioDetalleView.as_view(), name="usuario-detalle"),
    path(
        "usuarios/<int:pk>/restablecer-clave",
        views.RestablecerClaveView.as_view(),
        name="usuario-restablecer-clave",
    ),
]
