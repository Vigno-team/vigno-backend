import os
import json
from django.test import TestCase
from django.core.management import call_command
from django.conf import settings

class ExportacionFicticiaTest(TestCase):
    def test_json_completo(self):
        call_command('exportar_prediccion_ficticia')
        
        output_path = os.path.join(settings.BASE_DIR, 'data', 'cliente', 'vigno-prediccion-ficticia.json')
        self.assertTrue(os.path.exists(output_path))
        
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        self.assertTrue(data.get('datos_ficticios'))
        self.assertIn('generado', data)
        self.assertIn('fuente', data)
        self.assertEqual(data['fuente']['doi'], "10.6084/m9.figshare.19807777")
        self.assertIn('convencion_fechas', data)
        self.assertIn('modelo', data)
        self.assertIn('temporadas', data)
        self.assertIsInstance(data['temporadas'], list)
