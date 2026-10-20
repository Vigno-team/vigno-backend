import json
import os
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = 'Exporta el JSON de predicción con datos ficticios para el frontend'

    def handle(self, *args, **options):
        data = {
            "generado": datetime.now().isoformat() + "Z",
            "datos_ficticios": True,
            "fuente": {
                "cita": "Grape harvest dates and climate of California (Bai et al. 2022, Scientific Data 9:271)",
                "doi": "10.6084/m9.figshare.19807777",
                "licencia": "CC BY 4.0"
            },
            "convencion_fechas": "Se ajusta el día del año de California sumando 6 meses para proyectar fechas de cosecha en Chile.",
            "correlaciones": {
                "temp_acumulada_vs_dia_cosecha": -0.75,
                "precipitacion_vs_dia_cosecha": 0.2
            },
            "calidad": {
                "escala": "1 (Baja) a 5 (Alta)"
            },
            "modelo": {
                "variables": ["temp_acumulada", "precipitacion"],
                "importancias": {
                    "temp_acumulada": 0.65,
                    "precipitacion": 0.35
                },
                "metricas": {
                    "supera_base_ingenua": True,
                    "mae_dias": 5.2,
                    "rmse_dias": 6.8
                }
            },
            "temporadas": [
                {
                    "estacion": "Cauquenes",
                    "temporada_vigno": "2025",
                    "indices": {"temp_acumulada": 1450, "precipitacion": 300},
                    "ventana_estimada": {"inicio": "2025-03-15", "fin": "2025-03-25"},
                    "anios_analogos": [2018, 2020]
                }
            ]
        }

        output_dir = os.path.join(settings.BASE_DIR, 'data', 'cliente')
        os.makedirs(output_dir, exist_ok=True)
        
        output_path = os.path.join(output_dir, 'vigno-prediccion-ficticia.json')
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        self.stdout.write(self.style.SUCCESS(f'Archivo exportado exitosamente en: {output_path}'))
