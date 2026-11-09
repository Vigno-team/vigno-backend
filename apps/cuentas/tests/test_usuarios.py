import pytest
from django.contrib.auth import get_user_model
from rest_framework import status

from apps.auditoria.models import RegistroAuditoria
from apps.cuentas.models import debe_cambiar_clave
from apps.cuentas.roles import EDITOR, LECTOR

pytestmark = pytest.mark.django_db

URL_USUARIOS = "/api/v1/usuarios"

User = get_user_model()

CLAVE_TEMPORAL = "T3mp0ral-Usuario!2026"


def test_administrador_puede_listar_usuarios(cliente_admin):
    respuesta = cliente_admin.get(URL_USUARIOS)

    assert respuesta.status_code == status.HTTP_200_OK


def test_lector_no_puede_listar_usuarios(cliente_lector):
    respuesta = cliente_lector.get(URL_USUARIOS)

    assert respuesta.status_code == status.HTTP_403_FORBIDDEN


def test_editor_no_puede_listar_usuarios(cliente_con_token):
    respuesta = cliente_con_token.get(URL_USUARIOS)

    assert respuesta.status_code == status.HTTP_403_FORBIDDEN


def test_administrador_puede_crear_usuario(cliente_admin):
    datos = {
        "nombre": "Usuario Nuevo",
        "email": "nuevo@vigno.cl",
        "rol": EDITOR,
        "clave_temporal": CLAVE_TEMPORAL,
    }

    respuesta = cliente_admin.post(
        URL_USUARIOS,
        datos,
        format="json",
    )

    assert respuesta.status_code == status.HTTP_201_CREATED
    assert respuesta.data["email"] == datos["email"]
    assert respuesta.data["rol"] == EDITOR
    assert respuesta.data["activo"] is True
    assert respuesta.data["debe_cambiar_clave"] is True

    usuario = User.objects.get(email=datos["email"])

    assert usuario.check_password(CLAVE_TEMPORAL)
    assert debe_cambiar_clave(usuario) is True


def test_no_se_puede_crear_usuario_con_correo_duplicado(
    cliente_admin,
    usuario,
):
    datos = {
        "nombre": "Otro Usuario",
        "email": usuario.email,
        "rol": EDITOR,
        "clave_temporal": CLAVE_TEMPORAL,
    }

    respuesta = cliente_admin.post(
        URL_USUARIOS,
        datos,
        format="json",
    )

    assert respuesta.status_code == status.HTTP_400_BAD_REQUEST
    assert User.objects.filter(email=usuario.email).count() == 1


def test_administrador_puede_consultar_usuario(cliente_admin, usuario):
    respuesta = cliente_admin.get(f"{URL_USUARIOS}/{usuario.pk}")

    assert respuesta.status_code == status.HTTP_200_OK
    assert respuesta.data["email"] == usuario.email
    assert respuesta.data["rol"] == EDITOR


def test_administrador_puede_editar_usuario(cliente_admin, usuario):
    datos = {
        "nombre": "Nombre Modificado",
        "rol": LECTOR,
    }

    respuesta = cliente_admin.patch(
        f"{URL_USUARIOS}/{usuario.pk}",
        datos,
        format="json",
    )

    assert respuesta.status_code == status.HTTP_200_OK
    assert respuesta.data["nombre"] == "Nombre Modificado"
    assert respuesta.data["rol"] == LECTOR

    usuario.refresh_from_db()

    assert usuario.first_name == "Nombre Modificado"


def test_administrador_puede_desactivar_y_reactivar_usuario(
    cliente_admin,
    usuario,
):
    url = f"{URL_USUARIOS}/{usuario.pk}"

    # Desactivar
    respuesta = cliente_admin.patch(
        url,
        {"activo": False},
        format="json",
    )

    assert respuesta.status_code == status.HTTP_200_OK

    usuario.refresh_from_db()
    assert usuario.is_active is False

    # Reactivar
    respuesta = cliente_admin.patch(
        url,
        {"activo": True},
        format="json",
    )

    assert respuesta.status_code == status.HTTP_200_OK

    usuario.refresh_from_db()
    assert usuario.is_active is True


def test_delete_desactiva_sin_eliminar_usuario(cliente_admin, usuario):
    respuesta = cliente_admin.delete(f"{URL_USUARIOS}/{usuario.pk}")

    assert respuesta.status_code == status.HTTP_204_NO_CONTENT

    usuario.refresh_from_db()
    assert usuario.is_active is False
    assert User.objects.filter(pk=usuario.pk).exists()


def test_administrador_no_puede_desactivarse_a_si_mismo(cliente_admin):
    administrador = User.objects.get(email="admin@vigno.cl")

    respuesta = cliente_admin.delete(f"{URL_USUARIOS}/{administrador.pk}")

    assert respuesta.status_code == status.HTTP_400_BAD_REQUEST

    administrador.refresh_from_db()
    assert administrador.is_active is True


def test_administrador_no_puede_quitarse_su_propio_rol(cliente_admin):
    administrador = User.objects.get(email="admin@vigno.cl")

    respuesta = cliente_admin.patch(
        f"{URL_USUARIOS}/{administrador.pk}",
        {"rol": EDITOR},
        format="json",
    )

    assert respuesta.status_code == status.HTTP_400_BAD_REQUEST

    administrador.refresh_from_db()
    assert administrador.groups.filter(name="administrador").exists()


def test_administrador_puede_restablecer_clave(cliente_admin, usuario):
    respuesta = cliente_admin.post(
        f"{URL_USUARIOS}/{usuario.pk}/restablecer-clave",
        {"clave_temporal": CLAVE_TEMPORAL},
        format="json",
    )

    assert respuesta.status_code == status.HTTP_204_NO_CONTENT

    usuario.refresh_from_db()

    assert usuario.check_password(CLAVE_TEMPORAL)
    assert debe_cambiar_clave(usuario) is True


def test_filtrar_usuarios_por_rol(cliente_admin, usuario):
    respuesta = cliente_admin.get(
        URL_USUARIOS,
        {"rol": EDITOR},
    )

    assert respuesta.status_code == status.HTTP_200_OK
    assert all(item["rol"] == EDITOR for item in respuesta.data)
    assert any(item["id"] == usuario.pk for item in respuesta.data)


def test_filtrar_usuarios_activos(cliente_admin, usuario):
    usuario.is_active = False
    usuario.save(update_fields=["is_active"])

    respuesta = cliente_admin.get(
        URL_USUARIOS,
        {"activo": "true"},
    )

    assert respuesta.status_code == status.HTTP_200_OK
    assert all(item["activo"] is True for item in respuesta.data)
    assert not any(item["id"] == usuario.pk for item in respuesta.data)


def test_filtrar_usuarios_con_rol_invalido(cliente_admin):
    respuesta = cliente_admin.get(
        URL_USUARIOS,
        {"rol": "supervisor"},
    )

    assert respuesta.status_code == status.HTTP_400_BAD_REQUEST


def test_filtrar_usuarios_con_estado_invalido(cliente_admin):
    respuesta = cliente_admin.get(
        URL_USUARIOS,
        {"activo": "quizas"},
    )

    assert respuesta.status_code == status.HTTP_400_BAD_REQUEST


def test_creacion_usuario_registra_auditoria(cliente_admin):
    cliente_admin.post(
        URL_USUARIOS,
        {
            "nombre": "Auditoria",
            "email": "auditoria@vigno.cl",
            "rol": EDITOR,
            "clave_temporal": CLAVE_TEMPORAL,
        },
        format="json",
    )

    registro = RegistroAuditoria.objects.get(
        accion="usuario_alta",
        id_objeto=str(User.objects.get(email="auditoria@vigno.cl").pk),
    )

    assert registro.usuario.email == "admin@vigno.cl"
    assert "password" not in registro.valor_nuevo
    assert "clave_temporal" not in registro.valor_nuevo


def test_edicion_usuario_registra_auditoria(cliente_admin, usuario):
    cliente_admin.patch(
        f"{URL_USUARIOS}/{usuario.pk}",
        {"nombre": "Nombre Auditado"},
        format="json",
    )

    registro = RegistroAuditoria.objects.filter(
        accion="usuario_edicion",
        id_objeto=str(usuario.pk),
    ).latest("pk")

    assert registro.valor_anterior["first_name"] != "Nombre Auditado"
    assert registro.valor_nuevo["first_name"] == "Nombre Auditado"


def test_desactivacion_patch_registra_baja(cliente_admin, usuario):
    cliente_admin.patch(
        f"{URL_USUARIOS}/{usuario.pk}",
        {"activo": False},
        format="json",
    )

    assert RegistroAuditoria.objects.filter(
        accion="usuario_baja",
        id_objeto=str(usuario.pk),
    ).exists()


def test_delete_registra_baja(cliente_admin, usuario):
    cliente_admin.delete(f"{URL_USUARIOS}/{usuario.pk}")

    assert RegistroAuditoria.objects.filter(
        accion="usuario_baja",
        id_objeto=str(usuario.pk),
    ).exists()


def test_restablecimiento_no_guarda_clave_en_auditoria(
    cliente_admin,
    usuario,
):
    cliente_admin.post(
        f"{URL_USUARIOS}/{usuario.pk}/restablecer-clave",
        {"clave_temporal": CLAVE_TEMPORAL},
        format="json",
    )

    registro = RegistroAuditoria.objects.filter(
        accion="clave_cambiada",
        id_objeto=str(usuario.pk),
    ).latest("pk")

    assert "password" not in str(registro.valor_nuevo).lower()
    assert CLAVE_TEMPORAL not in str(registro.valor_nuevo)


@pytest.mark.parametrize(
    "cliente_fixture",
    ["cliente_con_token", "cliente_lector"],
)
@pytest.mark.parametrize(
    "operacion",
    ["crear", "editar", "eliminar", "restablecer"],
)
def test_roles_no_administradores_no_pueden_gestionar_usuarios(
    request,
    usuario,
    cliente_fixture,
    operacion,
):
    cliente = request.getfixturevalue(cliente_fixture)

    if operacion == "crear":
        respuesta = cliente.post(
            URL_USUARIOS,
            {
                "nombre": "Usuario Bloqueado",
                "email": "bloqueado@vigno.cl",
                "rol": EDITOR,
                "clave_temporal": CLAVE_TEMPORAL,
            },
            format="json",
        )

    elif operacion == "editar":
        respuesta = cliente.patch(
            f"{URL_USUARIOS}/{usuario.pk}",
            {"nombre": "Intento de edición"},
            format="json",
        )

    elif operacion == "eliminar":
        respuesta = cliente.delete(
            f"{URL_USUARIOS}/{usuario.pk}",
        )

    else:
        respuesta = cliente.post(
            f"{URL_USUARIOS}/{usuario.pk}/restablecer-clave",
            {"clave_temporal": CLAVE_TEMPORAL},
            format="json",
        )

    assert respuesta.status_code == status.HTTP_403_FORBIDDEN
