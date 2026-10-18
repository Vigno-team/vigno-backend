from django.db import migrations


def corregir_propietario_san_clemente(apps, schema_editor):
    Estacion = apps.get_model("clima", "Estacion")
    Estacion.objects.filter(nombre="San Clemente").update(propietario="Casas Patronales")


class Migration(migrations.Migration):
    dependencies = [("clima", "0010_auto_20261002_1516")]
    operations = [
        migrations.RunPython(corregir_propietario_san_clemente, migrations.RunPython.noop)
    ]