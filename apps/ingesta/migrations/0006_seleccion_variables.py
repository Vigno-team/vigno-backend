from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ingesta", "0005_hash_y_rango_de_fechas")]

    operations = [
        migrations.AddField(
            model_name="registrocarga",
            name="variables_procesadas",
            field=models.JSONField(
                default=list,
                blank=True,
                help_text="Variables que se han ingerido desde este archivo",
            ),
        ),
        migrations.AddField(
            model_name="registrocarga",
            name="variables_excluidas",
            field=models.JSONField(
                default=list,
                blank=True,
                help_text="Variables omitidas o desactivadas por el administrador",
            ),
        ),
    ]
