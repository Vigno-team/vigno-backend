from django.db import migrations

ROLES = ("administrador", "editor", "lector")

def crear_grupos(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for nombre in ROLES:
        Group.objects.get_or_create(name=nombre)


def borrar_grupos(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=ROLES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("cuentas", "0001_correo_unico"),
    ]

    operations = [
        migrations.RunPython(crear_grupos, borrar_grupos),
    ]