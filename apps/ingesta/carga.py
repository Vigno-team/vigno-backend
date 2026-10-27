"""Lectura, validación y guardado de un Excel de estación.

Lo comparten el comando ingestar_excel (terminal) y POST /api/v1/cargas (E1C-66).
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.clima.models import Estacion, MedicionHoraria
from apps.clima.rangos import cargar_rangos, motivo_fuera_de_rango
from apps.ingesta.models import RegistroCarga

MOTIVO_FECHA_INVALIDA = "Fecha vacía o inválida en una fila con datos"
MOTIVO_FECHA_REPETIDA = "Fecha repetida en el archivo"
MOTIVO_FECHA_FUTURA = "Fecha futura o sin datos posteriores"
MOTIVO_HORA_AMBIGUA = "Hora ambigua por cambio de horario"
AVISO_VACIO_CONSERVADO = "Celda vacía: se conservó el valor anterior"

ORIGEN_APROXIMADO = "ultimo año con fechas (aproximado)"


class ErrorCarga(ValueError):
    """El archivo completo no se puede cargar; `errores` trae los motivos legibles."""

    def __init__(self, errores):
        self.errores = [errores] if isinstance(errores, str) else list(errores)
        super().__init__(" ".join(self.errores))


@dataclass
class LimpiezaResult:
    df_limpio: pd.DataFrame
    crudo: pd.DataFrame
    rechazos: list[dict[str, Any]]
    columnas_abejas: list[str]
    filas_leidas: int
    filas_vacias_ignoradas: int = 0


@dataclass
class ClasificacionResult:
    a_guardar: list[MedicionHoraria]
    insertados: int
    actualizados: int
    sin_cambio: int
    omitidos: int
    # celdas vacías que no reemplazaron un valor existente: no son fallas, el dato sigue en la base
    conservados: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Preparacion:
    """Todo lo que se sabe del archivo antes de tocar la base."""

    estacion: Estacion
    formato: str
    frecuencia: str
    map_cols: dict
    temporada: int
    origen_temporada: str
    offset_fila: int
    limpieza: LimpiezaResult

    @property
    def fechas(self) -> pd.Series:
        return self.limpieza.df_limpio[self.map_cols["timestamp"]]

    def rango_fechas(self) -> tuple[date | None, date | None]:
        if self.fechas.empty:
            return None, None
        return self.fechas.min().date(), self.fechas.max().date()

    def advertencias(self) -> list[str]:
        avisos = []
        if self.origen_temporada == ORIGEN_APROXIMADO:
            avisos.append(
                f"La temporada {self.temporada} se dedujo de las fechas: no aparece en el título "
                "ni en el nombre del archivo. Indícala si no es correcta."
            )
        if self.limpieza.columnas_abejas:
            avisos.append(
                "Se descartaron las columnas de abejas: "
                + ", ".join(map(str, self.limpieza.columnas_abejas))
            )
        return avisos


def hash_archivo(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def cargar_umbrales(ruta=None) -> dict:
    ruta = ruta or settings.BASE_DIR / "config" / "validacion_cargas.json"
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def abrir_excel(origen) -> pd.ExcelFile:
    """`origen` es una ruta o un archivo en memoria (lo subido por la API)."""
    try:
        return pd.ExcelFile(origen)
    except Exception as exc:
        # openpyxl, xlrd y zipfile lanzan errores distintos para lo mismo: no se puede abrir
        raise ErrorCarga(
            "No se pudo abrir el archivo: está dañado, protegido con contraseña "
            "o no es un Excel .xls/.xlsx."
        ) from exc


def _hoja(excel: pd.ExcelFile, nombre_hoja):
    if isinstance(nombre_hoja, int):
        return nombre_hoja
    for hoja in excel.sheet_names:
        if str(hoja).strip().casefold() == str(nombre_hoja).casefold():
            return hoja
    raise ErrorCarga(
        f"El archivo no tiene la hoja '{nombre_hoja}'. "
        f"Hojas encontradas: {', '.join(map(str, excel.sheet_names))}."
    )


def _registrar_rechazos(rechazos, indices, originales, motivo, offset_fila):
    for i in indices:
        rechazos.append(
            {
                "fila": int(i) + offset_fila,
                "valor_original": str(originales.loc[i]),
                "motivo": motivo,
            }
        )


def detectar_temporada(excel, nombre_hoja, skip_rows, nombre_archivo, fechas):
    """Busca 'TEMPORADA 2024' en el titulo; si no, en el nombre del archivo."""
    titulo = pd.read_excel(excel, sheet_name=nombre_hoja, header=None, nrows=skip_rows)
    for celda in titulo.to_numpy().ravel():
        m = re.search(r"TEMPORADA\s*(\d{4})", str(celda), flags=re.IGNORECASE)
        if m:
            return int(m.group(1)), "titulo del Excel"

    anios = re.findall(r"(?:19|20)\d{2}", str(nombre_archivo).rsplit(".", 1)[0])
    if anios:
        return int(anios[-1]), "nombre del archivo"

    if len(fechas):
        return int(fechas.dt.year.max()), ORIGEN_APROXIMADO

    raise ErrorCarga(
        "No se pudo determinar la temporada: no aparece en el título ni en el nombre del "
        "archivo. Indica la temporada (año, por ejemplo 2024)."
    )


def leer_excel(excel, nombre_hoja, skip_rows: int) -> pd.DataFrame:
    try:
        df_headers = pd.read_excel(
            excel,
            sheet_name=nombre_hoja,
            header=None,
            skiprows=skip_rows,
            nrows=2,
        )
    except ValueError as e:
        raise ErrorCarga(f"No se pudo leer la hoja '{nombre_hoja}' del archivo.") from e
    if len(df_headers) < 2:
        raise ErrorCarga(
            f"La hoja '{nombre_hoja}' no tiene las dos filas de encabezado en la fila "
            f"{skip_rows + 1}."
        )

    grupo_superior = df_headers.iloc[0].ffill()
    nombres_columnas = []
    for g, s in zip(grupo_superior, df_headers.iloc[1], strict=True):
        g_str = "" if pd.isna(g) else str(g).strip()
        s_str = "" if pd.isna(s) else str(s).strip()
        nombre = f"{g_str}|{s_str}" if g_str and s_str else (g_str or s_str)
        nombres_columnas.append(nombre)

    if len(nombres_columnas) != len(set(nombres_columnas)):
        raise ErrorCarga("Existen columnas duplicadas despues de aplanar el encabezado.")

    df = pd.read_excel(
        excel,
        sheet_name=nombre_hoja,
        header=None,
        skiprows=skip_rows + 3,
        names=nombres_columnas,
    )
    return df


def _legible(columna: str) -> str:
    return columna.replace("|", " / ")


def detectar_formato(df: pd.DataFrame, config: dict, nombre_estacion: str) -> tuple[str, dict, str]:
    faltantes = {}
    for nombre_fmt, info_fmt in config["formatos"].items():
        columnas_requeridas = list(info_fmt["columnas"].values())
        faltan = [col for col in columnas_requeridas if col not in df.columns]
        if not faltan:
            return (
                nombre_fmt,
                info_fmt["columnas"],
                info_fmt.get("frecuencia", "D"),
            )
        faltantes[nombre_fmt] = faltan

    parecido = min(faltantes, key=lambda nombre: len(faltantes[nombre]))
    raise ErrorCarga(
        f"El archivo no calza con ningún formato conocido de {nombre_estacion}. "
        f"Respecto del formato más parecido ({parecido}) faltan las columnas: "
        f"{', '.join(_legible(c) for c in faltantes[parecido])}."
    )


def limpiar_y_rechazar(
    df: pd.DataFrame, map_cols: dict, frecuencia: str, tz_name: str, offset_fila: int
) -> LimpiezaResult:
    filas_leidas = len(df)

    columnas_abejas = [c for c in df.columns if "abeja" in str(c).lower()]
    df = df.drop(columns=columnas_abejas)

    col_fecha = map_cols["timestamp"]
    columnas_variables = [c for k, c in map_cols.items() if k != "timestamp"]

    # Espacios y celdas vacías de la plantilla no son mediciones rechazadas.
    columnas_origen = [col_fecha, *columnas_variables]
    vacias = (
        df[columnas_origen]
        .apply(
            lambda columna: columna.isna()
            | columna.map(lambda valor: isinstance(valor, str) and not valor.strip())
        )
        .all(axis=1)
    )
    filas_vacias_ignoradas = int(vacias.sum())
    df = df.loc[~vacias].copy()

    fechas_originales = df[col_fecha].copy()
    crudo = df[columnas_variables].copy()
    rechazos = []

    # 1. Fechas invalidas
    df[col_fecha] = pd.to_datetime(df[col_fecha], errors="coerce")
    invalidas = df[col_fecha].isna()
    _registrar_rechazos(
        rechazos,
        df.index[invalidas.to_numpy()],
        fechas_originales,
        MOTIVO_FECHA_INVALIDA,
        offset_fila,
    )
    df = df[~invalidas].copy()

    # 2. Zona horaria
    tz = ZoneInfo(tz_name)
    if frecuencia == "D":
        df[col_fecha] = (df[col_fecha].dt.normalize() + pd.Timedelta(hours=12)).dt.tz_localize(tz)
    else:
        # La hora repetida de abril y la que no existe en septiembre no se pueden ubicar
        # con certeza: se rechazan esas filas en vez de botar la carga completa.
        df[col_fecha] = df[col_fecha].dt.tz_localize(tz, nonexistent="NaT", ambiguous="NaT")
        dudosas = df[col_fecha].isna()
        _registrar_rechazos(
            rechazos,
            df.index[dudosas.to_numpy()],
            fechas_originales,
            MOTIVO_HORA_AMBIGUA,
            offset_fila,
        )
        df = df[~dudosas].copy()

    # 3. Fechas repetidas
    repetidas = df[col_fecha].duplicated(keep="first")
    _registrar_rechazos(
        rechazos,
        df.index[repetidas.to_numpy()],
        fechas_originales,
        MOTIVO_FECHA_REPETIDA,
        offset_fila,
    )
    df = df[~repetidas].copy()

    # 4. Valores numericos
    for col in columnas_variables:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 5. Dias futuros
    hoy = timezone.localdate()
    fechas_dia = df[col_fecha].dt.date
    tiene_dato = df[columnas_variables].notna().any(axis=1)
    futuras = fechas_dia > hoy
    if tiene_dato.any():
        futuras = futuras | (fechas_dia > fechas_dia[tiene_dato].max())
    _registrar_rechazos(
        rechazos,
        df.index[futuras.to_numpy()],
        fechas_originales,
        MOTIVO_FECHA_FUTURA,
        offset_fila,
    )
    df = df[~futuras].copy()

    rechazos.sort(key=lambda r: r["fila"])

    return LimpiezaResult(
        df, crudo, rechazos, columnas_abejas, filas_leidas, filas_vacias_ignoradas
    )


def preparar(
    origen,
    nombre_archivo: str,
    estacion: Estacion,
    config: dict,
    temporada: int | None = None,
    origen_temporada: str = "indicada",
) -> Preparacion:
    """Lee el Excel y deja todo listo para guardar. Lanza ErrorCarga si no sirve."""
    excel = abrir_excel(origen)
    nombre_hoja = _hoja(excel, config.get("sheet_name", 0))
    skip_rows = config["skip_rows"]
    # offset_fila: skip_rows + 4 es la fila 1-based en Excel (2 de encabezado, 1 de separacion, 1 porque es 1-based)
    offset_fila = skip_rows + 4

    df_raw = leer_excel(excel, nombre_hoja, skip_rows)
    formato, map_cols, frecuencia = detectar_formato(df_raw, config, estacion.nombre)
    limpieza = limpiar_y_rechazar(df_raw, map_cols, frecuencia, config["zona_horaria"], offset_fila)
    if not temporada:
        temporada, origen_temporada = detectar_temporada(
            excel, nombre_hoja, skip_rows, nombre_archivo, limpieza.df_limpio[map_cols["timestamp"]]
        )
    return Preparacion(
        estacion,
        formato,
        frecuencia,
        map_cols,
        temporada,
        origen_temporada,
        offset_fila,
        limpieza,
    )


def _pct(parte: int, total: int) -> float:
    return 100 * parte / total if total else 0.0


def validar_umbrales(prep: Preparacion, umbrales: dict) -> list[str]:
    """Reglas de E1C-66 para rechazar el archivo completo; los umbrales van en el JSON."""
    errores = []
    limpieza = prep.limpieza
    con_datos = limpieza.filas_leidas - limpieza.filas_vacias_ignoradas

    invalidas = sum(1 for r in limpieza.rechazos if r["motivo"] == MOTIVO_FECHA_INVALIDA)
    pct_invalidas = _pct(invalidas, con_datos)
    if pct_invalidas > umbrales["max_pct_fechas_invalidas"]:
        errores.append(
            f"El {pct_invalidas:.0f} % de las fechas son inválidas ({invalidas} de {con_datos} "
            f"filas); el máximo es {umbrales['max_pct_fechas_invalidas']} %."
        )

    df = limpieza.df_limpio
    if df.empty:
        errores.append("No quedó ninguna fila válida para cargar.")
        return errores

    for variable in umbrales["columnas_principales"]:
        columna = prep.map_cols.get(variable)
        if columna is None:
            continue
        vacias = int(df[columna].isna().sum())
        pct = _pct(vacias, len(df))
        if pct > umbrales["max_pct_principales_vacias"]:
            errores.append(
                f"La columna {_legible(columna)} viene vacía o no numérica en el {pct:.0f} % "
                f"de las filas ({vacias} de {len(df)}); el máximo es "
                f"{umbrales['max_pct_principales_vacias']} %."
            )
    return errores


def clasificar_cambios(
    df: pd.DataFrame,
    crudo: pd.DataFrame,
    map_cols: dict,
    estacion_obj: Estacion,
    frecuencia: str,
    temporada: int,
    offset_fila: int = 0,
) -> ClasificacionResult:
    col_fecha = map_cols["timestamp"]
    existentes = {}
    catalogo = cargar_rangos()

    if len(df):
        filas_bd = MedicionHoraria.objects.filter(
            estacion=estacion_obj,
            frecuencia=frecuencia,
            timestamp__gte=df[col_fecha].min().to_pydatetime(),
            timestamp__lte=df[col_fecha].max().to_pydatetime(),
        ).values_list(
            "timestamp",
            "variable",
            "valor",
            "temporada",
            "fuera_de_rango",
            "motivo_fuera_de_rango",
        )
        existentes = {
            (ts, var): (val, temp, flag, razon) for ts, var, val, temp, flag, razon in filas_bd
        }

    a_guardar = []
    conservados = []
    insertados = actualizados = sin_cambio = omitidos = 0

    for idx, row in df.iterrows():
        timestamp_local = row[col_fecha].to_pydatetime()

        for variable_canonica, col_excel in map_cols.items():
            if variable_canonica == "timestamp":
                continue

            valor_nuevo = row[col_excel]
            original = crudo.at[idx, col_excel]
            if pd.isna(valor_nuevo):
                valor_final = None
                if pd.isna(original):
                    motivo = "Dato en blanco en origen"
                else:
                    motivo = f"Valor no numérico en origen: {original!r}"[:255]
            else:
                valor_final = float(valor_nuevo)
                motivo = None

            motivo_rango = motivo_fuera_de_rango(
                variable_canonica, valor_final, frecuencia, catalogo
            )
            previo = existentes.get((timestamp_local, variable_canonica))
            if previo is None:
                insertados += 1
            else:
                valor_previo, temporada_previa, flag_previo, motivo_previo = previo
                if temporada_previa is not None and temporada_previa > temporada:
                    omitidos += 1
                    continue
                # Un vacío nunca reemplaza un valor existente (E1C-66; E1C-132 usa la misma regla).
                if valor_final is None and valor_previo is not None:
                    sin_cambio += 1
                    conservados.append(
                        {
                            "fila": int(idx) + offset_fila,
                            "fecha": timezone.localdate(timestamp_local).isoformat(),
                            "variable": variable_canonica,
                        }
                    )
                    continue
                if (
                    valor_previo == valor_final
                    and flag_previo == bool(motivo_rango)
                    and motivo_previo == motivo_rango
                ):
                    sin_cambio += 1
                    continue
                actualizados += 1

            # Comentarios requeridos por deuda técnica
            # NOTA: MedicionHoraria guarda también datos diarios (frecuencia="D"), con la hora forzada a las 12:00 para evitar el cambio de hora.
            # NOTA: temporada es el año del archivo (2024), no la temporada agronómica (2024-2025). Sirve solo para prevalencia al recargar.
            a_guardar.append(
                MedicionHoraria(
                    estacion=estacion_obj,
                    timestamp=timestamp_local,
                    variable=variable_canonica,
                    frecuencia=frecuencia,
                    valor=valor_final,
                    motivo_nulo=motivo,
                    fuera_de_rango=bool(motivo_rango),
                    motivo_fuera_de_rango=motivo_rango,
                    temporada=temporada,
                )
            )

    return ClasificacionResult(
        a_guardar, insertados, actualizados, sin_cambio, omitidos, conservados
    )


def clasificar(prep: Preparacion) -> ClasificacionResult:
    limpieza = prep.limpieza
    return clasificar_cambios(
        limpieza.df_limpio,
        limpieza.crudo,
        prep.map_cols,
        prep.estacion,
        prep.frecuencia,
        prep.temporada,
        prep.offset_fila,
    )


def guardar(
    prep: Preparacion,
    r_clas: ClasificacionResult,
    archivo: str,
    hash_del_archivo: str | None = None,
    usuario: str | None = None,
) -> RegistroCarga:
    r_limp = prep.limpieza
    if r_limp.columnas_abejas:
        notas_descarte = (
            f"Se descartaron {len(r_limp.columnas_abejas)} columnas de abejas: "
            f"{', '.join(map(str, r_limp.columnas_abejas))}"
        )[:255]
    else:
        notas_descarte = "Sin descartes"
    desde, hasta = prep.rango_fechas()

    # RegistroCarga se crea antes de la transaccion para auditar el intento aunque falle
    extra = {"usuario": usuario} if usuario else {}
    carga_obj = RegistroCarga.objects.create(
        archivo=archivo,
        hash_archivo=hash_del_archivo,
        estacion=prep.estacion.nombre,
        formato_detectado=prep.formato,
        temporada=prep.temporada,
        fecha_desde=desde,
        fecha_hasta=hasta,
        filas_leidas=r_limp.filas_leidas,
        filas_vacias_ignoradas=r_limp.filas_vacias_ignoradas,
        filas_aceptadas=len(r_limp.df_limpio),
        filas_rechazadas=len(r_limp.rechazos),
        detalle_rechazos=r_limp.rechazos,
        celdas_vacias_conservadas=r_clas.conservados,
        columnas_descartadas=notas_descarte,
        **extra,
    )

    for medicion in r_clas.a_guardar:
        medicion.carga = carga_obj

    try:
        with transaction.atomic():
            MedicionHoraria.objects.bulk_create(
                r_clas.a_guardar,
                batch_size=1000,
                update_conflicts=True,
                unique_fields=["estacion", "timestamp", "variable", "frecuencia"],
                update_fields=[
                    "valor",
                    "motivo_nulo",
                    "carga",
                    "temporada",
                    "fuera_de_rango",
                    "motivo_fuera_de_rango",
                ],
            )
    except Exception as e:
        carga_obj.estado = RegistroCarga.ESTADO_FALLIDA
        carga_obj.error = str(e)
        carga_obj.save()
        raise

    carga_obj.registros_insertados = r_clas.insertados
    carga_obj.registros_actualizados = r_clas.actualizados
    carga_obj.registros_sin_cambio = r_clas.sin_cambio
    carga_obj.registros_omitidos = r_clas.omitidos
    carga_obj.save()

    return carga_obj
