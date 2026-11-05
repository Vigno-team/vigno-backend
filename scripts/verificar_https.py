"""Prueba HTTP/HTTPS contra un despliegue local aislado (no modifica datos)."""

import argparse
import http.client
import json
import ssl
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://localhost")
    parser.add_argument("--http-url", default="http://localhost")
    parser.add_argument("--cert", default="deploy/certs/fullchain.pem")
    args = parser.parse_args()
    https, origen_http = urlsplit(args.url), urlsplit(args.http_url)
    if https.hostname not in {"localhost", "127.0.0.1"} or origen_http.hostname != https.hostname:
        parser.error("Usar un despliegue local de prueba, no el servidor del cliente.")
    contexto = ssl.create_default_context(cafile=args.cert)

    def consultar(ruta, *, seguro=True, metodo="GET", headers=None):
        if seguro:
            conexion = http.client.HTTPSConnection(
                https.hostname, https.port or 443, context=contexto, timeout=20
            )
        else:
            conexion = http.client.HTTPConnection(
                origen_http.hostname, origen_http.port or 80, timeout=20
            )
        try:
            conexion.request(metodo, ruta, headers=headers or {})
            respuesta = conexion.getresponse()
            return respuesta.status, dict(respuesta.getheaders()), respuesta.read()
        finally:
            conexion.close()

    estado, headers, _ = consultar("/api/v1/datos?prueba=1", seguro=False)
    assert estado == 308, (estado, headers)
    destino = urlsplit(headers["Location"])
    assert destino.scheme == "https" and destino.hostname == https.hostname
    assert (destino.port or 443) == (https.port or 443)
    assert destino.path == "/api/v1/datos" and destino.query == "prueba=1"

    for ruta, esperado in (
        ("/", 200),
        ("/api/health/", 200),
        ("/api/v1/datos", 200),
        ("/api/v1/actualizacion", 200),
        ("/admin/", 404),
        ("/api/docs/", 404),
        ("/api/schema/", 404),
        ("/api/v1/no-existe-e134", 404),
    ):
        estado, headers, cuerpo = consultar(ruta, headers={"X-Forwarded-Proto": "http"})
        assert estado == esperado, (ruta, estado, cuerpo[:200])
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "camera=()" in headers["Permissions-Policy"]
        assert "default-src 'self'" in headers["Content-Security-Policy"]
        assert "https://server.arcgisonline.com" in headers["Content-Security-Policy"]
        assert "max-age=3600" in headers["Strict-Transport-Security"]
        assert headers.get("Server") == "nginx", headers.get("Server")
        if ruta == "/api/v1/datos":
            json.loads(cuerpo)
            assert headers["Cache-Control"] == "no-cache"
            estado_etag, _, _ = consultar(ruta, headers={"If-None-Match": headers["ETag"]})
            assert estado_etag == 304
        print(f"OK {ruta}: {estado}, cabeceras de seguridad")

    estado, headers, _ = consultar(
        "/api/v1/cargas",
        metodo="OPTIONS",
        headers={
            "Origin": args.url.rstrip("/"),
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,if-none-match",
        },
    )
    assert estado == 200
    minusculas = {k.lower(): v for k, v in headers.items()}
    assert minusculas["access-control-allow-origin"] == args.url.rstrip("/")
    assert "authorization" in minusculas["access-control-allow-headers"]
    assert "if-none-match" in minusculas["access-control-allow-headers"]
    for ruta in ("/api/v1/auth/token", "/api/v1/auth/cambiar-clave", "/api/v1/cargas"):
        estados = [consultar(ruta)[0] for _ in range(16)]
        assert 429 in estados, (ruta, estados)
        print(f"OK límite por IP en {ruta}: HTTP 429")
    for ruta in ("/api/v1/auth/refresh", "/api/v1/auth/yo", "/api/v1/auth/logout"):
        estados = [consultar(ruta)[0] for _ in range(16)]
        assert all(estado in (401, 405) for estado in estados), (ruta, estados)
        print(f"OK {ruta}: sin bloqueo por el límite de login")
    print("HTTPS, redirección, ETag, CORS, rutas cerradas y límites: OK")


if __name__ == "__main__":
    main()
