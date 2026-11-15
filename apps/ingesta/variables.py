"""Variables de los Excel y dependencias que muestra el administrador."""

VARIABLES = {
    "temperatura_media": {"nombre": "Temperatura media", "unidad": "°C"},
    "temperatura_maxima": {"nombre": "Temperatura máxima", "unidad": "°C"},
    "temperatura_minima": {"nombre": "Temperatura mínima", "unidad": "°C"},
    "precipitacion": {"nombre": "Precipitación", "unidad": "mm"},
    "humedad_media": {"nombre": "Humedad relativa media", "unidad": "%"},
    "radiacion_maxima": {"nombre": "Radiación máxima", "unidad": "W/m²"},
    "viento_maximo": {"nombre": "Velocidad máxima del viento", "unidad": "m/s"},
}

# Cada lista interior reúne requisitos simultáneos; las listas exteriores son alternativas.
# Los últimos tres indicadores dependen de índices, no directamente de una sola columna.
DEPENDENCIAS_INDICADORES = {
    "winkler": [["temperatura_media"], ["temperatura_maxima", "temperatura_minima"]],
    "huglin": [
        ["temperatura_maxima", "temperatura_media"],
        ["temperatura_maxima", "temperatura_minima"],
    ],
    "dias_criticos": [["temperatura_maxima"]],
    "calor_extremo": [["temperatura_maxima"]],
    "rachas": [["temperatura_maxima"]],
    "amplitud_termica": [["temperatura_maxima", "temperatura_minima"]],
    "lluvia_invernal": [["precipitacion"]],
    "lluvia_fuera_invierno": [["precipitacion"]],
    "clasificacion": [["winkler", "huglin", "lluvia_invernal"]],
    "anos_analogos": [["winkler", "huglin", "lluvia_invernal"]],
    "prediccion": [["winkler", "huglin", "lluvia_invernal"]],
}


def indicadores_de(variable):
    """Incluye dependencias directas e indirectas, sin ocultar las alternativas."""
    afectados = {variable}
    for indicador, alternativas in DEPENDENCIAS_INDICADORES.items():
        if any(requisito in afectados for alternativa in alternativas for requisito in alternativa):
            afectados.add(indicador)
    return [indicador for indicador in DEPENDENCIAS_INDICADORES if indicador in afectados]


def catalogo_variables():
    return [
        {"variable": variable, **datos, "indicadores": indicadores_de(variable)}
        for variable, datos in VARIABLES.items()
    ]
