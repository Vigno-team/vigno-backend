from apps.clima.models import MedicionHoraria, IndiceClimatico, Estacion

def obtener_datos_estacion_agrupados(nombre_estacion: str, fecha_inicio, fecha_fin):
    """
    Obtiene las mediciones de la base de datos y las agrupa por dia usando 
    un diccionario de Python muy simple.
    """
    # Traemos solo los registros necesarios de la base de datos
    mediciones = MedicionHoraria.objects.filter(
        estacion__nombre=nombre_estacion,
        timestamp__date__range=[fecha_inicio, fecha_fin],
        variable__in=["temperatura_maxima", "temperatura_minima"]
    )
    
    # Agrupamos los datos por fecha: {fecha: {"temperatura_maxima": 30, "temperatura_minima": 10}}
    datos_por_dia = {}
    for medicion in mediciones:
        fecha = medicion.timestamp.date()
        if fecha not in datos_por_dia:
            datos_por_dia[fecha] = {}
        
        datos_por_dia[fecha][medicion.variable] = medicion.valor
        
    return datos_por_dia


def calcular_indice_winkler(nombre_estacion: str, fecha_inicio, fecha_fin, temporada: str = None, temp_base: float = 10.0) -> float:
    """
    Calcula el Indice de Winkler usando matematicas basicas (sin librerias complejas).
    """
    datos_por_dia = obtener_datos_estacion_agrupados(nombre_estacion, fecha_inicio, fecha_fin)
    
    total_winkler = 0.0
    
    # Recorremos dia por dia
    for fecha, variables in datos_por_dia.items():
        # Nos aseguramos de tener ambas temperaturas para ese dia
        if "temperatura_maxima" in variables and "temperatura_minima" in variables:
            t_max = variables["temperatura_maxima"]
            t_min = variables["temperatura_minima"]
            
            # Calculo de la media
            t_media = (t_max + t_min) / 2.0
            
            # Grados dia activos (solo suma si la temperatura media supera la base)
            grados_activos = t_media - temp_base
            if grados_activos > 0:
                total_winkler += grados_activos
                
    # Si se nos paso una temporada, guardamos el resultado
    if temporada:
        estacion = Estacion.objects.get(nombre=nombre_estacion)
        IndiceClimatico.objects.update_or_create(
            estacion=estacion,
            temporada=temporada,
            indice="Winkler",
            defaults={
                "valor": total_winkler,
                "parametros": {
                    "fecha_inicio": str(fecha_inicio),
                    "fecha_fin": str(fecha_fin),
                    "temp_base": temp_base
                }
            }
        )
        
    return total_winkler


def calcular_indice_huglin(nombre_estacion: str, fecha_inicio, fecha_fin, temporada: str = None, k: float = 1.0, temp_base: float = 10.0) -> float:
    """
    Calcula el Indice de Huglin usando matematicas basicas (sin librerias complejas).
    """
    datos_por_dia = obtener_datos_estacion_agrupados(nombre_estacion, fecha_inicio, fecha_fin)
    
    total_huglin = 0.0
    
    # Recorremos dia por dia
    for fecha, variables in datos_por_dia.items():
        if "temperatura_maxima" in variables and "temperatura_minima" in variables:
            t_max = variables["temperatura_maxima"]
            t_min = variables["temperatura_minima"]
            
            t_media = (t_max + t_min) / 2.0
            
            # Formula de Huglin: suma de [(T_media - 10) + (T_max - 10)] / 2
            # Solo sumamos si el resultado del dia es positivo
            calculo_diario = ((t_media - temp_base) + (t_max - temp_base)) / 2.0
            
            if calculo_diario > 0:
                # Se multiplica por K que depende de la latitud
                total_huglin += (calculo_diario * k)
                
    # Guardamos el historial
    if temporada:
        estacion = Estacion.objects.get(nombre=nombre_estacion)
        IndiceClimatico.objects.update_or_create(
            estacion=estacion,
            temporada=temporada,
            indice="Huglin",
            defaults={
                "valor": total_huglin,
                "parametros": {
                    "fecha_inicio": str(fecha_inicio),
                    "fecha_fin": str(fecha_fin),
                    "k": k,
                    "temp_base": temp_base
                }
            }
        )
        
    return total_huglin
