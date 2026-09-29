from datetime import date
import pandas as pd
from apps.clima.models import ConfiguracionCalidad, SerieDiaria

def cargar_serie_diaria(df_diario: pd.DataFrame) -> list[SerieDiaria]:
    """Guarda los registros diarios y calcula la amplitud térmica (E1C-25)."""
    if df_diario.empty:
        return []

    # Limpieza básica para evitar strings en campos numéricos
    cols_num = ["temperatura_media", "temperatura_maxima", "temperatura_minima"]
    for col in cols_num:
        df_diario[col] = pd.to_numeric(df_diario[col], errors="coerce")
    
    df_diario["fecha"] = pd.to_datetime(df_diario["timestamp"], errors="coerce").dt.date
    df_diario = df_diario.dropna(subset=["estacion", "fecha"])
    
    registros_guardados = []
    
    for _, row in df_diario.iterrows():
        tmax = round(float(row["temperatura_maxima"]), 2) if pd.notna(row["temperatura_maxima"]) else None
        tmin = round(float(row["temperatura_minima"]), 2) if pd.notna(row["temperatura_minima"]) else None
        tmedia = round(float(row["temperatura_media"]), 2) if pd.notna(row["temperatura_media"]) else None
        
        amplitud = round(tmax - tmin, 2) if tmax is not None and tmin is not None else None

        obj, _ = SerieDiaria.objects.update_or_create(
            estacion=row["estacion"],
            fecha=row["fecha"],
            defaults={
                "tmax": tmax,
                "tmin": tmin,
                "tmedia": tmedia,
                "amplitud_termica": amplitud,
            },
        )
        registros_guardados.append(obj)

    return registros_guardados

def consultar_completitud_periodo(estacion: str, fecha_inicio: date, fecha_fin: date) -> dict:
    """Evalúa la completitud en días para un rango dado (E1C-26 y E1C-27)."""
    dias_esperados = (fecha_fin - fecha_inicio).days + 1
    if dias_esperados <= 0:
        raise ValueError("El rango de fechas es inválido.")

    # Cuenta cuántos días reales tienen registro de temperatura media
    dias_validos = SerieDiaria.objects.filter(
        estacion=estacion,
        fecha__gte=fecha_inicio,
        fecha__lte=fecha_fin,
        tmedia__isnull=False
    ).count()

    completitud_pct = round((dias_validos / dias_esperados) * 100.0, 2)
    umbral = ConfiguracionCalidad.obtener_umbral()

    return {
        "estacion": estacion,
        "dias_validos": dias_validos,
        "dias_esperados": dias_esperados,
        "completitud_pct": completitud_pct,
        "es_confiable": completitud_pct >= umbral,
    }