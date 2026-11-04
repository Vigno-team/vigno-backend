from django.db import migrations

# Se entra con el correo (E1C-64): no puede haber dos cuentas con el mismo, sin distinguir
# mayúsculas. Se usa el User de Django sin modelo propio, así que el índice se crea a mano.
# Las cuentas sin correo (email vacío) quedan fuera: no pueden entrar por la API.


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE UNIQUE INDEX cuentas_correo_unico ON auth_user (UPPER(email)) WHERE email <> '';",
            reverse_sql="DROP INDEX IF EXISTS cuentas_correo_unico;",
        ),
    ]
