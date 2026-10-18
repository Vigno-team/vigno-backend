from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("clima", "0011_corregir_estaciones"),
    ]

    operations = [
        migrations.AddField(
            model_name="estacion",
            name="longitud",
            field=models.FloatField(blank=True, null=True),
        ),
    ]