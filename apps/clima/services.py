from datetime import date
import pandas as pd
from apps.clima.models import ConfiguracionCalidad, SerieDiaria

ZONA_CHILE = "America/Santiago"

def cargar_serie_diaria(df_diario: pd.DataFrame) -> list[SerieDiaria]:
    """Guarda registros diarios directos y calcula la amplitud térmica."""
    if df_diario.empty:
        return []

    cols_num = ["temperatura_media", "temperatura_maxima", "temperatura_minima"]
    for col in cols_num:
        df_diario[col] = pd.to_numeric(df_diario[col], errors="coerce")
    
    # errors="coerce" convierte el "00:00" en nulo para que dropna lo elimine.
    # tz_convert asegura que las 23:00 horas no salten al día siguiente por diferencias UTC.
    fechas_dt = pd.to_datetime(df_diario["timestamp"], errors="coerce", utc=True)
    df_diario["fecha"] = fechas_dt.dt.tz_convert(ZONA_CHILE).dt.date
    
    # Se elimina cualquier fila que haya quedado sin fecha o sin estación válida
    df_diario = df_diario.dropna(subset=["estacion", "fecha"])
    
    registros = []
    
    # Se usa groupby por estación y fecha para absorber duplicados
    for (estacion, fecha), grupo in df_diario.groupby(["estacion", "fecha"]):
        row = grupo.iloc[-1]
        
        tmax = round(float(row["temperatura_maxima"]), 2) if pd.notna(row["temperatura_maxima"]) else None
        tmin = round(float(row["temperatura_minima"]), 2) if pd.notna(row["temperatura_minima"]) else None
        tmedia = round(float(row["temperatura_media"]), 2) if pd.notna(row["temperatura_media"]) else None
        
        amplitud = round(tmax - tmin, 2) if tmax is not None and tmin is not None else None

        obj, _ = SerieDiaria.objects.update_or_create(
            estacion=estacion,
            fecha=fecha,
            defaults={"tmax": tmax, "tmin": tmin, "tmedia": tmedia, "amplitud_termica": amplitud}
        )
        registros.append(obj)

    return registros


def consultar_completitud_periodo(estacion: str, fecha_inicio: date, fecha_fin: date) -> dict:
    """Evalúa la completitud en días."""
    dias_esperados = (fecha_fin - fecha_inicio).days + 1
    if dias_esperados <= 0:
        raise ValueError("Rango inválido")

    dias_validos = SerieDiaria.objects.filter(
        estacion=estacion, fecha__gte=fecha_inicio, fecha__lte=fecha_fin, tmedia__isnull=False
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