import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytz
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.clima.models import Estacion, MedicionHoraria
from apps.ingesta.models import RegistroCarga

MOTIVO_FECHA_INVALIDA = "Fecha inválida"
MOTIVO_FECHA_REPETIDA = "Fecha repetida en el archivo"
MOTIVO_FECHA_FUTURA = "Fecha futura o sin datos posteriores"


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

    @staticmethod
    def _registrar_rechazos(rechazos, indices, originales, motivo, offset_fila):
        for i in indices:
            rechazos.append(
                {
                    "fila": int(i) + offset_fila,
                    "valor_original": str(originales.loc[i]),
                    "motivo": motivo,
                }
            )

    @staticmethod
    def _detectar_temporada(archivo_path, nombre_hoja, skip_rows, fechas):
        """Busca 'TEMPORADA 2024' en el titulo; si no, en el nombre del archivo."""
        titulo = pd.read_excel(archivo_path, sheet_name=nombre_hoja, header=None, nrows=skip_rows)
        for celda in titulo.to_numpy().ravel():
            m = re.search(r"TEMPORADA\s*(\d{4})", str(celda), flags=re.IGNORECASE)
            if m:
                return int(m.group(1)), "titulo del Excel"

        anios = re.findall(r"(?:19|20)\d{2}", Path(archivo_path).stem)
        if anios:
            return int(anios[-1]), "nombre del archivo"

        if len(fechas):
            return int(fechas.dt.year.max()), "ultimo año con fechas (aproximado)"

        raise CommandError("No se pudo determinar la temporada. Usa --temporada AAAA.")

    def handle(self, *args, **options):
        archivo_path = options["archivo"]
        nombre_estacion = options["estacion"]

        if not Path(archivo_path).is_file():
            raise CommandError(f"El archivo {archivo_path} no existe.")

        config_path = settings.BASE_DIR / "config" / "mapeos_estaciones.json"
        with open(config_path, encoding="utf-8") as f:
            mapeos = json.load(f)

        if nombre_estacion not in mapeos:
            raise CommandError(f"No hay mapeo configurado para la estacion '{nombre_estacion}'")

        config = mapeos[nombre_estacion]
        nombre_hoja = config.get("sheet_name", 0)
        skip_rows = config["skip_rows"]
        offset_fila = skip_rows + 4

        self.stdout.write(f"Iniciando lectura de {archivo_path} (hoja: {nombre_hoja})...")

        # Encabezados de 2 niveles
        try:
            df_headers = pd.read_excel(
                archivo_path,
                sheet_name=nombre_hoja,
                header=None,
                skiprows=skip_rows,
                nrows=2,
            )
        except ValueError as e:
            raise CommandError(f"No se pudo leer la hoja '{nombre_hoja}' del archivo.") from e

        grupo_superior = df_headers.iloc[0].ffill()
        nombres_columnas = []
        for g, s in zip(grupo_superior, df_headers.iloc[1], strict=True):
            g_str = "" if pd.isna(g) else str(g).strip()
            s_str = "" if pd.isna(s) else str(s).strip()
            nombre = f"{g_str}|{s_str}" if g_str and s_str else (g_str or s_str)
            nombres_columnas.append(nombre)

        if len(nombres_columnas) != len(set(nombres_columnas)):
            raise CommandError("Existen columnas duplicadas despues de aplanar el encabezado.")

        # Datos reales
        df = pd.read_excel(
            archivo_path,
            sheet_name=nombre_hoja,
            header=None,
            skiprows=skip_rows + 3,
            names=nombres_columnas,
        )

        # Detectar formato
        formato_detectado = None
        map_cols = None
        frecuencia = None

        for nombre_fmt, info_fmt in config["formatos"].items():
            columnas_requeridas = list(info_fmt["columnas"].values())
            if all(col in df.columns for col in columnas_requeridas):
                formato_detectado = nombre_fmt
                map_cols = info_fmt["columnas"]
                frecuencia = info_fmt.get("frecuencia", "D")
                break

        if not formato_detectado:
            raise CommandError(
                f"El archivo no calza con ningun formato conocido de {nombre_estacion}. "
                f"Columnas encontradas: {list(df.columns)}"
            )

        self.stdout.write(f"Formato detectado: {formato_detectado} (Frecuencia: {frecuencia})")

        # Descartar abejas
        columnas_abejas = [c for c in df.columns if "abeja" in str(c).lower()]
        df = df.drop(columns=columnas_abejas)

        filas_leidas = len(df)
        col_fecha = map_cols["timestamp"]
        columnas_variables = [c for k, c in map_cols.items() if k != "timestamp"]

        # Copias del valor original para poder explicar los rechazos y los nulos
        fechas_originales = df[col_fecha].copy()
        crudo = df[columnas_variables].copy()
        rechazos = []

        # Fechas invalidas
        df[col_fecha] = pd.to_datetime(df[col_fecha], errors="coerce")
        invalidas = df[col_fecha].isna()
        self._registrar_rechazos(
            rechazos,
            df.index[invalidas.to_numpy()],
            fechas_originales,
            MOTIVO_FECHA_INVALIDA,
            offset_fila,
        )
        df = df[~invalidas].copy()

        # Zona horaria (cambio de hora chileno)
        tz = pytz.timezone(config["zona_horaria"])
        if frecuencia == "D":
            # Diario: forzar mediodia para evadir el cambio de hora de medianoche
            df[col_fecha] = (df[col_fecha].dt.normalize() + pd.Timedelta(hours=12)).dt.tz_localize(
                tz
            )
        else:
            df[col_fecha] = df[col_fecha].dt.tz_localize(
                tz, nonexistent="shift_forward", ambiguous="infer"
            )

        # Fechas repetidas dentro del mismo archivo: gana la primera
        repetidas = df[col_fecha].duplicated(keep="first")
        self._registrar_rechazos(
            rechazos,
            df.index[repetidas.to_numpy()],
            fechas_originales,
            MOTIVO_FECHA_REPETIDA,
            offset_fila,
        )
        df = df[~repetidas].copy()

        # Valores numericos
        for col in columnas_variables:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Dias futuros y plantilla vacia posterior al ultimo dato
        hoy = datetime.now(tz).date()
        fechas_dia = df[col_fecha].dt.date
        tiene_dato = df[columnas_variables].notna().any(axis=1)
        futuras = fechas_dia > hoy
        if tiene_dato.any():
            futuras = futuras | (fechas_dia > fechas_dia[tiene_dato].max())
        self._registrar_rechazos(
            rechazos,
            df.index[futuras.to_numpy()],
            fechas_originales,
            MOTIVO_FECHA_FUTURA,
            offset_fila,
        )
        df = df[~futuras].copy()

        rechazos.sort(key=lambda r: r["fila"])

        # Temporada
        if options["temporada"]:
            temporada, origen = options["temporada"], "argumento --temporada"
        else:
            temporada, origen = self._detectar_temporada(
                archivo_path, nombre_hoja, skip_rows, df[col_fecha]
            )
        self.stdout.write(f"Temporada: {temporada} (fuente: {origen})")

        # Datos ya existentes en el rango, para aplicar la regla de temporada
        estacion_obj, _ = Estacion.objects.get_or_create(nombre=nombre_estacion)

        existentes = {}
        if len(df):
            filas_bd = MedicionHoraria.objects.filter(
                estacion=estacion_obj,
                frecuencia=frecuencia,
                timestamp__gte=df[col_fecha].min().to_pydatetime(),
                timestamp__lte=df[col_fecha].max().to_pydatetime(),
            ).values_list("timestamp", "variable", "valor", "temporada")
            existentes = {(ts, var): (val, temp) for ts, var, val, temp in filas_bd}

        # Estandarizar y clasificar
        a_guardar = []
        insertados = actualizados = sin_cambio = omitidos = 0

        for idx, row in df.iterrows():
            timestamp_local = row[col_fecha].to_pydatetime()

            for variable_canonica, col_excel in map_cols.items():
                if variable_canonica == "timestamp":
                    continue

                valor_nuevo = row[col_excel]
                if pd.isna(valor_nuevo):
                    valor_final = None
                    original = crudo.at[idx, col_excel]
                    if pd.isna(original):
                        motivo = "Dato en blanco en origen"
                    else:
                        motivo = f"Valor no numérico en origen: {original!r}"[:255]
                else:
                    valor_final = float(valor_nuevo)
                    motivo = None

                previo = existentes.get((timestamp_local, variable_canonica))
                if previo is None:
                    insertados += 1
                else:
                    valor_previo, temporada_previa = previo
                    if temporada_previa is not None and temporada_previa > temporada:
                        omitidos += 1  # ya hay un dato de una temporada mas nueva
                        continue
                    if valor_previo == valor_final:
                        sin_cambio += 1
                        continue
                    actualizados += 1

                a_guardar.append(
                    MedicionHoraria(
                        estacion=estacion_obj,
                        timestamp=timestamp_local,
                        variable=variable_canonica,
                        frecuencia=frecuencia,
                        valor=valor_final,
                        motivo_nulo=motivo,
                        temporada=temporada,
                    )
                )

        # Registro de carga
        if columnas_abejas:
            notas_descarte = (
                f"Se descartaron {len(columnas_abejas)} columnas de abejas: "
                f"{', '.join(map(str, columnas_abejas))}"
            )[:255]
        else:
            notas_descarte = "Sin descartes"

        carga_obj = RegistroCarga.objects.create(
            archivo=archivo_path,
            estacion=nombre_estacion,
            formato_detectado=formato_detectado,
            temporada=temporada,
            filas_leidas=filas_leidas,
            filas_aceptadas=len(df),
            filas_rechazadas=len(rechazos),
            detalle_rechazos=rechazos,
            columnas_descartadas=notas_descarte,
        )

        for medicion in a_guardar:
            medicion.carga = carga_obj

        try:
            with transaction.atomic():
                MedicionHoraria.objects.bulk_create(
                    a_guardar,
                    batch_size=1000,
                    update_conflicts=True,
                    unique_fields=["estacion", "timestamp", "variable", "frecuencia"],
                    update_fields=["valor", "motivo_nulo", "carga", "temporada"],
                )
        except Exception as e:
            # Queda constancia del intento fallido
            carga_obj.estado = RegistroCarga.ESTADO_FALLIDA
            carga_obj.error = str(e)
            carga_obj.save()
            raise CommandError(f"Error al insertar en la base de datos: {e}") from e

        carga_obj.registros_insertados = insertados
        carga_obj.registros_actualizados = actualizados
        carga_obj.registros_sin_cambio = sin_cambio
        carga_obj.registros_omitidos = omitidos
        carga_obj.save()

        # Reporte final
        out = self.stdout.write
        out(self.style.SUCCESS("\n=== REPORTE DE INGESTA VIGNO ==="))
        out(f"Estación: {nombre_estacion} | Formato: {formato_detectado} | Temporada: {temporada}")
        out(f"Filas leídas totales: {filas_leidas}")
        out(self.style.SUCCESS(f"Filas válidas procesadas: {len(df)}"))

        if rechazos:
            out(self.style.WARNING(f"Filas rechazadas: {len(rechazos)} (ver detalle_rechazos)"))
        if columnas_abejas:
            out(
                self.style.WARNING(
                    f"Regla de Negocio: Se descartaron {len(columnas_abejas)} columna(s) de abejas."
                )
            )

        out(
            f"\nVariables individuales evaluadas: {insertados + actualizados + sin_cambio + omitidos}"
        )
        out(self.style.SUCCESS(f" -> Insertadas nuevas: {insertados}"))
        out(self.style.WARNING(f" -> Actualizadas con cambio: {actualizados}"))
        out(f" -> Sin cambio (ya existían igual): {sin_cambio}")
        out(f" -> Omitidas (ya venían de una temporada más nueva): {omitidos}")
        out(self.style.SUCCESS("================================\n"))
