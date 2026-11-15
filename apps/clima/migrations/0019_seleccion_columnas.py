from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("clima", "0018_estacion_activa")]

    operations = [
        migrations.AddField(
            model_name="medicionhoraria",
            name="excluido",
            field=models.BooleanField(default=False, db_index=True),
        ),
        migrations.AddField(
            model_name="resumendiario",
            name="humedad_media",
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="resumendiario",
            name="radiacion_maxima",
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="resumendiario",
            name="viento_maximo",
            field=models.FloatField(null=True, blank=True),
        ),
    ]
