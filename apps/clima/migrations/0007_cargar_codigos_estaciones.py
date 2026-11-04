from django.db import migrations

ESTACIONES = {
    
    "El Arenal": ("cp-villavicencio-01", "villavicencio", "Casas Patronales"),
    "San Clemente": ("cp-san-clemente-01", "san-clemente", "Casas Ptronales"),
}


def cargar(apps, schema_editor):
    Estacion = apps.get_model("clima", "Estacion")
    for nombre, (codigo, subzona, propietario) in ESTACIONES.items():
        Estacion.objects.update_or_create(
            nombre=nombre,
            defaults={"codigo": codigo, "subzona": subzona, "propietario": propietario},
        )


class Migration(migrations.Migration):
    dependencies = [("clima", "0006_configuracioncalidad_estacion_codigo_and_more")]
    # E1C-95: solo cargar_instancia incorpora el catálogo. Las bases ya migradas
    # conservan sus filas; no se agrega ninguna operación de borrado.
    operations = []
