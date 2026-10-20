from django.core.management.base import BaseCommand
from apps.clima.prediccion.evaluacion import EvaluadorVentanaCosecha

class Command(BaseCommand):
    help = 'Entrena el modelo de predicción de cosecha y evalúa'

    def handle(self, *args, **options):
        self.stdout.write('Iniciando entrenamiento y evaluación...')
        
        # Instanciar el evaluador
        evaluador = EvaluadorVentanaCosecha(umbral_acierto_dias=7)
        
        # Aquí irá tu lógica real de carga de datos y entrenamiento:
        # reporte_json = evaluador.generar_reporte_json(df_subset1, df_napa, modelo, features, target)
        
        self.stdout.write(self.style.SUCCESS('Evaluador integrado correctamente. ¡Listo para usar con datos reales!'))
