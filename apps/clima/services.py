from datetime import date
import pandas as pd
from apps.clima.models import ConfiguracionCalidad, ResumenDiario

def derivar_resumenes_diarios(df_ingesta: pd.DataFrame) -> list[ResumenDiario]:
    if df_ingesta.empty:
        return []

    #Limpieza básica
    cols_num = ["temperatura_media", "temperatura_maxima", "temperatura_minima"]
    for col in cols_num:
        if col in df_ingesta.columns:
            df_ingesta[col] = pd.to_numeric(df_ingesta[col], errors="coerce")
    
    df_ingesta["fecha"] = pd.to_datetime(df_ingesta["timestamp"], errors="coerce").dt.date
    df_ingesta = df_ingesta.dropna(subset=["estacion", "fecha", "frecuencia"])
    
    registros = []

    #Procesar datos que ya vienen DIARIOS ("D")
    df_diario = df_ingesta[df_ingesta["frecuencia"] == "D"]
    for _, row in df_diario.iterrows():
        tmax = round(float(row["temperatura_maxima"]), 2) if pd.notna(row.get("temperatura_maxima")) else None
        tmin = round(float(row["temperatura_minima"]), 2) if pd.notna(row.get("temperatura_minima")) else None
        tmedia = round(float(row["temperatura_media"]), 2) if pd.notna(row.get("temperatura_media")) else None
        amplitud = round(tmax - tmin, 2) if tmax is not None and tmin is not None else None

        obj, _ = ResumenDiario.objects.update_or_create(
            estacion=row["estacion"], fecha=row["fecha"],
            defaults={
                "tmax": tmax, "tmin": tmin, "tmedia": tmedia, "amplitud_termica": amplitud,
                "origen": "D", "horas_validas": None, "horas_esperadas": None
            }
        )
        registros.append(obj)

    #Procesar datos que vienen HORARIOS ("H") y calcular el resumen
    df_horario = df_ingesta[df_ingesta["frecuencia"] == "H"]
    if not df_horario.empty and "temperatura_media" in df_horario.columns:
        for (estacion, fecha), grupo in df_horario.groupby(["estacion", "fecha"]):
            serie_valida = grupo["temperatura_media"].dropna()
            horas_validas = int(serie_valida.count())

            if horas_validas > 0:
                tmax = round(float(serie_valida.max()), 2)
                tmin = round(float(serie_valida.min()), 2)
                tmedia = round(float(serie_valida.mean()), 2)
                amplitud = round(tmax - tmin, 2)
            else:
                tmax = tmin = tmedia = amplitud = None

            obj, _ = ResumenDiario.objects.update_or_create(
                estacion=estacion, fecha=fecha,
                defaults={
                    "tmax": tmax, "tmin": tmin, "tmedia": tmedia, "amplitud_termica": amplitud,
                    "origen": "H", "horas_validas": horas_validas, "horas_esperadas": 24
                }
            )
            registros.append(obj)

    return registros

def consultar_completitud_periodo(estacion: str, fecha_inicio: date, fecha_fin: date) -> dict:
    dias_esperados = (fecha_fin - fecha_inicio).days + 1
    if dias_esperados <= 0:
        raise ValueError("Rango inválido")

    dias_validos = ResumenDiario.objects.filter(
        estacion=estacion, fecha__gte=fecha_inicio, fecha__lte=fecha_fin, tmedia__isnull=False
    ).count()

    completitud_pct = round((dias_validos / dias_esperados) * 100.0, 2)
    umbral = ConfiguracionCalidad.obtener_umbral()

    return {
        "estacion": estacion, "dias_validos": dias_validos, "dias_esperados": dias_esperados,
        "completitud_pct": completitud_pct, "es_confiable": completitud_pct >= umbral,
    }