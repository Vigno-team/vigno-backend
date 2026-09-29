import json
import pandas as pd
from pathlib import Path

from django.db import transaction
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import make_aware
import pytz

from apps.clima.models import Estacion, MedicionHoraria
from apps.ingesta.models import RegistroCarga

class Command(BaseCommand):
    help = 'Ingesta datos climaticos desde un Excel basandose en el mapeo configurable'

    def add_arguments(self, parser):
        # Argumentos obligatorios
        parser.add_argument('--archivo', type=str, required=True, help='Ruta al archivo Excel crudo')
        parser.add_argument('--estacion', type=str, required=True, help='Nombre de la estacion')

    def handle(self, *args, **options):
        archivo_path = options['archivo']
        nombre_estacion = options['estacion']

        # Validar que el archivo exista
        if not Path(archivo_path).is_file():
            raise CommandError(f"El archivo {archivo_path} no existe.")

        # Cargar configuracion
        config_path = settings.BASE_DIR / 'config' / 'mapeos_estaciones.json'
        with open(config_path, encoding='utf-8') as f:
            mapeos = json.load(f)

        if nombre_estacion not in mapeos:
            raise CommandError(f"No hay mapeo configurado para la estacion '{nombre_estacion}'")

        config = mapeos[nombre_estacion]
        nombre_hoja = config.get('sheet_name', 0)
        skip_rows = config['skip_rows']
        
        self.stdout.write(f"Iniciando lectura de {archivo_path} (hoja: {nombre_hoja})...")

        # Leer encabezados correctamente usando ffill
        try:
            df_headers = pd.read_excel(
                archivo_path, 
                sheet_name=nombre_hoja, 
                header=None, 
                skiprows=skip_rows, 
                nrows=2
            )
        except ValueError:
            raise CommandError(f"No se pudo leer la hoja '{nombre_hoja}' del archivo.")

        grupo_superior = df_headers.iloc[0].ffill()
        nombres_columnas = []
        for g, s in zip(grupo_superior, df_headers.iloc[1]):
            g_str = "" if pd.isna(g) else str(g).strip()
            s_str = "" if pd.isna(s) else str(s).strip()
            # Si ambos existen, se unen con |. Si no, se usa el que exista.
            nombre = f"{g_str}|{s_str}" if g_str and s_str else (g_str or s_str)
            nombres_columnas.append(nombre)
            
        if len(nombres_columnas) != len(set(nombres_columnas)):
            raise CommandError("Existen columnas duplicadas despues de aplanar el encabezado.")

        # Leer los datos reales saltando las filas de titulo, las 2 de encabezado y 1 vacia
        df = pd.read_excel(
            archivo_path,
            sheet_name=nombre_hoja,
            header=None,
            skiprows=skip_rows + 3,
            names=nombres_columnas
        )

        # Detectar formato y validar colmnas
        formato_detectado = None
        map_cols = None
        frecuencia = None
        
        for nombre_fmt, info_fmt in config['formatos'].items():
            columnas_requeridas = list(info_fmt['columnas'].values())
            # Si todas las columnas del formato estan en el dataframe, es nuestro formato
            if all(col in df.columns for col in columnas_requeridas):
                formato_detectado = nombre_fmt
                map_cols = info_fmt['columnas']
                frecuencia = info_fmt.get('frecuencia', 'D')
                break

        if not formato_detectado:
            raise CommandError(
                f"El archivo no calza con ningun formato conocido de {nombre_estacion}. "
                f"Columnas encontradas: {list(df.columns)}"
            )
            
        self.stdout.write(f"Formato detectado: {formato_detectado} (Frecuencia: {frecuencia})")

        # Descartar abejas
        columnas_abejas_descartadas = 0
        columnas_a_descartar = [c for c in df.columns if 'abeja' in str(c).lower()]
        for col in columnas_a_descartar:
            df.drop(columns=[col], inplace=True)
            columnas_abejas_descartadas += 1

        # Contadores para Trazabilidad
        filas_leidas = len(df)
        filas_rechazadas = 0
        filas_aceptadas = 0

        col_fecha = map_cols['timestamp']

        # Convertir la columna de fecha sin caerse
        df[col_fecha] = pd.to_datetime(df[col_fecha], errors="coerce")

        # Separar las rechazadas por fecha inválida
        invalid_dates_mask = df[col_fecha].isna()
        filas_rechazadas += invalid_dates_mask.sum()
        df = df[~invalid_dates_mask].copy()

        # Manejo de horas y cambio de horario chileno
        tz = pytz.timezone(config['zona_horaria'])

        if frecuencia == 'D':
            # Datos diarios: forzar al mediodía (12:00 PM) para evadir el cambio de hora de medianoche
            df[col_fecha] = df[col_fecha].dt.normalize() + pd.Timedelta(hours=12)
            df[col_fecha] = df[col_fecha].dt.tz_localize(tz)
        else:
            # Datos horarios
            df[col_fecha] = df[col_fecha].dt.tz_localize(tz, nonexistent="shift_forward", ambiguous="infer")

        # Forzar valores numéricos en variables para no caerse con textos como "s/d"
        columnas_variables = [c for k, c in map_cols.items() if k != 'timestamp']
        for col in columnas_variables:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        estacion_obj, _ = Estacion.objects.get_or_create(nombre=nombre_estacion)
        nuevas_mediciones = []

        # Iterar y estandarizar
        for _, row in df.iterrows():
            timestamp_local = row[col_fecha]
            filas_aceptadas += 1

            for variable_canonica, col_excel in map_cols.items():
                if variable_canonica == 'timestamp':
                    continue

                # Si la columna no existe en este Excel, se ignora, no se guarda como "blanco en origen"
                if col_excel not in df.columns:
                    continue

                valor_crudo = row.get(col_excel)
                es_nulo = pd.isna(valor_crudo)

                valor_final = None if es_nulo else float(valor_crudo)
                motivo = "Dato en blanco en origen o valor no numérico" if es_nulo else None

                medicion = MedicionHoraria(
                    estacion=estacion_obj,
                    timestamp=timestamp_local,
                    variable=variable_canonica,
                    valor=valor_final,
                    motivo_nulo=motivo
                )
                nuevas_mediciones.append(medicion)

        # Crear el registro de carga antes para poder asociarlo a las mediciones
        notas_descarte = f"Se descartaron {columnas_abejas_descartadas} columnas de abejas" if columnas_abejas_descartadas > 0 else "Sin descartes"
        
        carga_obj = RegistroCarga.objects.create(
            archivo=archivo_path,
            estacion=nombre_estacion,
            formato_detectado=formato_detectado,
            filas_leidas=filas_leidas,
            filas_aceptadas=filas_aceptadas,
            filas_rechazadas=filas_rechazadas,
            columnas_descartadas=notas_descarte
        )

        for medicion in nuevas_mediciones:
            medicion.frecuencia = frecuencia
            medicion.carga = carga_obj

        # Inserción en BD con control de conflictos
        total_bd_antes = MedicionHoraria.objects.filter(estacion=estacion_obj).count()

        try:
            with transaction.atomic():
                MedicionHoraria.objects.bulk_create(
                    nuevas_mediciones,
                    update_conflicts=True,
                    unique_fields=['estacion', 'timestamp', 'variable', 'frecuencia'],
                    update_fields=['valor', 'motivo_nulo', 'carga']
                )
        except Exception as e:
            # Si falla la transacción, limpiamos el registro huérfano de carga
            carga_obj.delete()
            raise CommandError(f"Error al insertar en la base de datos: {str(e)}")

        total_bd_despues = MedicionHoraria.objects.filter(estacion=estacion_obj).count()
        registros_insertados = total_bd_despues - total_bd_antes
        registros_actualizados = len(nuevas_mediciones) - registros_insertados

        # Guardar conteos reales
        carga_obj.registros_insertados = registros_insertados
        carga_obj.registros_actualizados = registros_actualizados
        carga_obj.save()

        # Reporte final
        self.stdout.write(self.style.SUCCESS("\n=== REPORTE DE INGESTA VIGNO ==="))
        self.stdout.write(f"Estación: {nombre_estacion} | Formato: {formato_detectado}")
        self.stdout.write(f"Filas leídas totales: {filas_leidas}")
        self.stdout.write(self.style.SUCCESS(f"Filas válidas procesadas: {filas_aceptadas}"))

        if filas_rechazadas > 0:
            self.stdout.write(self.style.WARNING(f"Filas ignoradas (fecha no válida): {filas_rechazadas}"))
        if columnas_abejas_descartadas > 0:
            self.stdout.write(self.style.WARNING(f"Regla de Negocio: Se descartaron {columnas_abejas_descartadas} columna(s) de abejas."))

        self.stdout.write(f"\nVariables individuales procesadas: {len(nuevas_mediciones)}")
        self.stdout.write(self.style.SUCCESS(f" -> Insertadas nuevas: {registros_insertados}"))
        self.stdout.write(self.style.WARNING(f" -> Actualizadas (Sobrescritas por archivo nuevo): {registros_actualizados}"))
        self.stdout.write(self.style.SUCCESS("================================\n"))