import json
import pandas as pd
from pathlib import Path
from django.core.management.base import BaseCommand
from django.utils.timezone import make_aware
import pytz
from apps.clima.models import Estacion, MedicionCanonica

class Command(BaseCommand):
    help = 'Ingesta datos climaticos desde un Excel basandose en el mapeo configurable'

    def add_arguments(self, parser):
        parser.add_argument('--archivo', type=str, help='Ruta al archivo Excel crudo')
        parser.add_argument('--estacion', type=str, help='Nombre de la estacion')

    def handle(self, *args, **options):
        archivo_path = options['archivo']
        nombre_estacion = options['estacion']

        # 1. Cargar configuracion
        config_path = Path('config/mapeos_estaciones.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            mapeos = json.load(f)

        if nombre_estacion not in mapeos:
            self.stdout.write(self.style.ERROR(f"No hay mapeo configurado para {nombre_estacion}"))
            return

        config = mapeos[nombre_estacion]
        map_cols = config['columnas']
        
        # 2. Leer Excel manejando cabeceras de 2 pisos
        nombre_hoja = config.get('sheet_name', 0)
        self.stdout.write(f"Iniciando lectura de {archivo_path} (hoja: {nombre_hoja})...")
        
        df = pd.read_excel(
            archivo_path, 
            sheet_name=nombre_hoja, 
            skiprows=config['skip_rows'],
            header=[0, 1]
        )

        # Aplanar cabeceras combinadas
        columnas_limpias = []
        for col_superior, col_inferior in df.columns:
            if 'Unnamed' in str(col_inferior) or str(col_inferior).strip() == '':
                columnas_limpias.append(str(col_superior).strip())
            else:
                columnas_limpias.append(str(col_inferior).strip())
        df.columns = columnas_limpias

        # Contadores para Trazabilidad
        filas_leidas = len(df)
        filas_aceptadas = 0
        filas_rechazadas = 0
        columnas_abejas_descartadas = 0

        # Verificar descarte de abejas por regla de negocio
        for col_rechazada in config.get('columnas_rechazadas', []):
            if col_rechazada in df.columns:
                columnas_abejas_descartadas += 1

        estacion_obj, _ = Estacion.objects.get_or_create(nombre=nombre_estacion)
        tz = pytz.timezone(config['zona_horaria'])
        nuevas_mediciones = []

        # 3. Iterar y estandarizar
        for index, row in df.iterrows():
            fecha_cruda = row.get(map_cols['timestamp'])
            
            # Si no hay fecha, se rechaza la fila completa
            if pd.isna(fecha_cruda):
                filas_rechazadas += 1
                continue 
            
            filas_aceptadas += 1
            timestamp_local = make_aware(fecha_cruda, timezone=tz)

            for variable_canonica, col_excel in map_cols.items():
                if variable_canonica == 'timestamp':
                    continue
                
                valor_crudo = row.get(col_excel)
                es_nulo = pd.isna(valor_crudo)
                
                valor_final = None if es_nulo else float(valor_crudo)
                motivo = "Dato en blanco en origen" if es_nulo else None

                medicion = MedicionCanonica(
                    estacion=estacion_obj,
                    timestamp=timestamp_local,
                    variable=variable_canonica,
                    valor=valor_final,
                    motivo_nulo=motivo
                )
                nuevas_mediciones.append(medicion)

        # 4. Insercion en BD
        MedicionCanonica.objects.bulk_create(nuevas_mediciones, ignore_conflicts=True)
        
        # 5. Reporte de Resultados en Terminal
        self.stdout.write(self.style.SUCCESS("\n=== REPORTE DE INGESTA VIGNO ==="))
        self.stdout.write(f"Estacion: {nombre_estacion}")
        self.stdout.write(f"Filas totales leidas en Excel: {filas_leidas}")
        self.stdout.write(self.style.SUCCESS(f"Filas validas procesadas: {filas_aceptadas}"))
        
        if filas_rechazadas > 0:
            self.stdout.write(self.style.WARNING(f"Filas ignoradas (sin fecha o vacias): {filas_rechazadas}"))
            
        if columnas_abejas_descartadas > 0:
            self.stdout.write(self.style.WARNING(f"Regla de Negocio: Se detectaron y descartaron {columnas_abejas_descartadas} columna(s) de abejas."))
            
        self.stdout.write(self.style.SUCCESS(f"Variables individuales guardadas en Base de Datos: {len(nuevas_mediciones)}"))
        self.stdout.write(self.style.SUCCESS("================================\n"))