from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.clima.management.commands.actualizar_todo import candado
from apps.clima.mapeos import EstacionNoExiste, estacion_y_mapeo
from apps.ingesta import carga


class Command(BaseCommand):
    help = "Ingesta datos climaticos desde un Excel basandose en el mapeo configurable"

    def add_arguments(self, parser):
        parser.add_argument("--archivo", type=str, required=True, help="Ruta al Excel crudo")
        parser.add_argument("--estacion", type=str, required=True, help="Nombre de la estacion")
        parser.add_argument(
            "--temporada",
            type=int,
            default=None,
            help="Año de la temporada (si se omite, se detecta del titulo o del nombre del archivo)",
        )

    def handle(self, *args, **options):
        archivo_path = options["archivo"]
        nombre_estacion = options["estacion"]

        if not Path(archivo_path).is_file():
            raise CommandError(f"El archivo {archivo_path} no existe.")

        # La estación debe estar registrada (se crea con POST /api/v1/estaciones). Usa su mapeo
        # propio o, si no tiene, la plantilla formato_estandar.
        try:
            estacion_obj, config = estacion_y_mapeo(nombre_estacion)
        except EstacionNoExiste as e:
            raise CommandError(str(e)) from e
        nombre_estacion = estacion_obj.nombre

        self.stdout.write(
            f"Iniciando lectura de {archivo_path} (hoja: {config.get('sheet_name', 0)})..."
        )
        # La lógica vive en apps.ingesta.carga, compartida con POST /api/v1/cargas (E1C-66).
        try:
            prep = carga.preparar(
                archivo_path,
                Path(archivo_path).name,
                estacion_obj,
                config,
                options["temporada"],
                origen_temporada="argumento --temporada",
            )
        except carga.ErrorCarga as e:
            raise CommandError(str(e)) from e
        self.stdout.write(f"Formato detectado: {prep.formato} (Frecuencia: {prep.frecuencia})")
        self.stdout.write(f"Temporada: {prep.temporada} (fuente: {prep.origen_temporada})")

        res_limpieza = prep.limpieza
        try:
            # Igual que la API: una corrección no puede entrar entre comparar y guardar.
            with candado():
                res_clas = carga.clasificar(prep)
                carga.guardar(
                    prep,
                    res_clas,
                    archivo_path,
                    carga.hash_archivo(Path(archivo_path).read_bytes()),
                )
        except Exception as e:
            raise CommandError(f"Error al insertar en la base de datos: {e}") from e

        out = self.stdout.write
        out(self.style.SUCCESS("\n=== REPORTE DE INGESTA VIGNO ==="))
        out(f"Estación: {nombre_estacion} | Formato: {prep.formato} | Temporada: {prep.temporada}")
        out(f"Filas leídas totales: {res_limpieza.filas_leidas}")
        out(f"Filas vacías ignoradas: {res_limpieza.filas_vacias_ignoradas}")
        out(self.style.SUCCESS(f"Filas válidas procesadas: {len(res_limpieza.df_limpio)}"))

        if res_limpieza.rechazos:
            out(
                self.style.WARNING(
                    f"Filas rechazadas: {len(res_limpieza.rechazos)} (ver detalle_rechazos)"
                )
            )
        if res_limpieza.columnas_abejas:
            out(
                self.style.WARNING(
                    f"Regla de Negocio: Se descartaron {len(res_limpieza.columnas_abejas)} columna(s) de abejas."
                )
            )
        if res_clas.conservados:
            out(
                self.style.WARNING(
                    f"Celdas vacías que no borraron un dato ya cargado: {len(res_clas.conservados)}"
                )
            )

        total_vars = (
            res_clas.insertados + res_clas.actualizados + res_clas.sin_cambio + res_clas.omitidos
        )
        out(f"\nVariables individuales evaluadas: {total_vars}")
        out(self.style.SUCCESS(f" -> Insertadas nuevas: {res_clas.insertados}"))
        out(self.style.WARNING(f" -> Actualizadas con cambio: {res_clas.actualizados}"))
        out(f" -> Sin cambio (ya existían igual): {res_clas.sin_cambio}")
        out(f" -> Omitidas (ya venían de una temporada más nueva): {res_clas.omitidos}")
        out(self.style.SUCCESS("================================\n"))
