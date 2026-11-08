"""Rutas raíz del servicio."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

from apps.clima.views import HealthCheckView

urlpatterns = [
    path("api/health/", HealthCheckView.as_view(), name="health-check"),
    path("api/v1/", include("apps.clima.urls")),
    path("api/v1/", include("apps.ingesta.urls")),
    path("api/v1/", include("apps.cuentas.urls")),
    path("api/v1/", include("apps.auditoria.urls")),
    path("api/v1/", include("apps.configuracion.urls")),
]

if settings.ADMIN_HABILITADO:
    urlpatterns.append(path("admin/", admin.site.urls))

if settings.DOCS_HABILITADOS:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path(
            "api/docs/",
            SpectacularSwaggerView.as_view(url_name="schema"),
            name="swagger-ui",
        ),
    ]

# El logo: en desarrollo lo sirve runserver. Con DEBUG=False static() no agrega
# nada y lo sirve nginx desde el volumen media.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
