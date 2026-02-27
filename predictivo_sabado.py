import os
import sys
import re
import unicodedata
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
 
import pandas as pd
from dotenv import load_dotenv
 
# ========================= Config/Constantes =========================
 
ALLOWED_RESULT_KEEP = {"ANSWER-MACHINE", "BUSY", "CONGESTION", "FAILED", "NO-ANSWER"}
 
CONSTANTES = {
    "ASESOR": "vigpromotora1",
    "CANAL": "HACER LLAMADA",
    "ESTADO CLIENTE": "No Contestan",
    "ESTADO CONTACTO": "SIN CONTACTO",
    "NIVEL1": "SIN CONTACTO",
    "NIVEL2": "No Contestan",
    "NIVEL3": "NO CONTESTAN",
    "NIVEL4": "SIN MOTIVO",
}
 
PROJECT_ROOT   = Path(__file__).resolve().parent
TEMPLATE_PATH  = PROJECT_ROOT / "formatoArbolProducto.csv"
PREDICTIVO_DIR = PROJECT_ROOT / "Predictivo"
OUTPUT_FILE    = PREDICTIVO_DIR / f"cargue_predictivo_{datetime.now(ZoneInfo('America/Bogota')).date()}.csv"
 
MULTICANAL_DIR = PROJECT_ROOT / "Multicanal"
MULTI_COL_ID   = "Número Identificación"
MULTI_COL_PROD = "Numero producto"
 
DATABRICKS_CSV_DIR = PROJECT_ROOT / "Predictivo"

def find_wolkvox_source_csv(folder: Path) -> Path:
    """
    Busca el CSV más reciente descargado por descarga_predictivo_sabado.py
    en la carpeta Predictivo/ (patron: wolkvox_campaign_3_*.csv).
    """
    if not folder.exists():
        raise FileNotFoundError(f"No existe la carpeta: {folder}")
    files = sorted(
        folder.glob("wolkvox_campaign_3_*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError(
            f"No se encontró ningún archivo wolkvox_campaign_3_*.csv en: {folder}"
        )
    return files[0]
 
FORMATO_COLUMNS = [
    "CEDULA","NUMERO TELEFONO","MENSAJE","ASESOR","FECHA GESTION","CANAL",
    "ESTADO CLIENTE","ESTADO CONTACTO","NIVEL1","NIVEL2","NIVEL3","NIVEL4",
    "NIVEL5","NIVEL6","NIVEL7","NIVEL8","NIVEL9","NIVEL10","NUMERO PRODUCTO"
]
 
# ========================= Utilidades =========================
 
def read_template_columns(path: Path) -> list:
    df_hdr = pd.read_csv(path, nrows=0, sep=";", dtype=str, engine="python")
    cols = [(c.strip() if isinstance(c, str) else c) for c in df_hdr.columns]
    cols = [c for c in cols if c and not str(c).lower().startswith("unnamed")]
    return cols
 
def ensure_cols(df: pd.DataFrame, cols: list):
    for c in cols:
        if c not in df.columns:
            df[c] = ""
 
def normalize_phone(x):
    if pd.isna(x):
        return None
 
    digits = ''.join(ch for ch in str(x) if ch.isdigit())
    if not digits:
        return None
 
    if digits.startswith("957"):
        digits = digits[3:]
    elif digits.startswith("9"):
        digits = digits[1:]
 
    if len(digits) != 10 or not digits.startswith("3"):
        return None
 
    try:
        return int(digits)
    except Exception:
        return None
 
def parse_date_any(s):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return pd.to_datetime(s, format=fmt, errors="raise")
        except Exception:
            pass
    return pd.to_datetime(s, errors="coerce")
 
def pick_latest_local_csv(folder: Path) -> Path:
    if not folder.exists():
        raise FileNotFoundError(f"No existe la carpeta: {folder}")
    files = [p for p in folder.glob("*.csv") if p.is_file()]
    if not files:
        raise FileNotFoundError(f"No se encontró ningún .csv en: {folder}")
    return max(files, key=lambda p: p.stat().st_mtime)
 
def read_multicanal_local(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, sep=";", dtype=str, encoding="utf-8", engine="python")
    except UnicodeDecodeError:
        return pd.read_csv(path, sep=";", dtype=str, encoding="latin-1", engine="python")
 
def clean_cedula_value(x) -> str:
    s = "" if pd.isna(x) else str(x).strip()
    s = re.sub(r"\.0$", "", s)
    s = s.replace(" ", "")
    return s
 
def sanitize_sms_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[¿¡]", "", text)
    text = re.sub(r"[^a-zA-Z0-9\s\.,;:\-_()]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
 
def build_multicanal_map(df_multi: pd.DataFrame) -> pd.DataFrame:
    if MULTI_COL_ID not in df_multi.columns:
        raise ValueError(f"Multicanal: no existe la columna obligatoria '{MULTI_COL_ID}'")
    if MULTI_COL_PROD not in df_multi.columns:
        raise ValueError(f"Multicanal: no existe la columna obligatoria '{MULTI_COL_PROD}'")
 
    tmp = df_multi[[MULTI_COL_ID, MULTI_COL_PROD]].copy()
    tmp.columns = ["CEDULA", "NUMERO PRODUCTO"]
 
    tmp["CEDULA"] = tmp["CEDULA"].apply(clean_cedula_value)
    tmp["NUMERO PRODUCTO"] = tmp["NUMERO PRODUCTO"].astype(str).str.strip().fillna("")
 
    tmp = tmp[tmp["CEDULA"].ne("")].copy()
    tmp = tmp.drop_duplicates(subset=["CEDULA"], keep="last")
    return tmp
 
# ========================= NUEVO: Lectura CSV Wolkvox =========================
 
def read_wolkvox_csv(path: Path) -> pd.DataFrame:
    """
    Lee el CSV que te enviaron (delimitador coma) y retorna DataFrame con strings.
    Intenta UTF-8 y luego Latin-1.
    """
    if not path.exists():
        raise FileNotFoundError(f"No existe el CSV fuente: {path}")
 
    try:
        df = pd.read_csv(path, sep=",", dtype=str, encoding="utf-8", engine="python")
    except UnicodeDecodeError:
        df = pd.read_csv(path, sep=",", dtype=str, encoding="latin-1", engine="python")
 
    # Normaliza nombres (por si llegan con espacios raros)
    df.columns = [c.strip() for c in df.columns]
    return df
 
# ========================= Transformación =========================
 
def build_cargue_from_df(df_campaign: pd.DataFrame, template_path: Path, multicanal_map: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "campaign_id": "CAMPAIGN_ID",
        "customer_name": "CUSTOMER_NAME",
        "customer_last_name": "CUSTOMER_LAST_NAME",
        "id_type": "TYPE_ID",
        "customer_id": "CUSTOMER_ID",
        "date": "DATE",
        "telephone": "TELEPHONE",
        "result": "RESULT",
        "opt1": "OPT1", "opt2": "OPT2", "opt3": "OPT3", "opt4": "OPT4", "opt5": "OPT5",
        "opt6": "OPT6", "opt7": "OPT7", "opt8": "OPT8", "opt9": "OPT9", "opt10": "OPT10",
        "opt11": "OPT11", "opt12": "OPT12", "conn_id": "CONN_ID"
    }
    df = df_campaign.rename(columns=rename_map).copy()
 
    required = {"CUSTOMER_ID", "TELEPHONE", "RESULT", "DATE"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas requeridas en la fuente: {missing}")
 
    # === FILTRO: quitar ANSWER ===
    df["RESULT"] = df["RESULT"].astype(str)
    df = df[~df["RESULT"].str.upper().eq("ANSWER")].copy()
 
    # Teléfono limpio
    df["NUM_TELEPHONE_CLEAN"] = df["TELEPHONE"].apply(normalize_phone)
 
    # MENSAJE (sanitizado)
    df["MENSAJE_TMP"] = ("llamada predictiva resultado: " + df["RESULT"].astype(str)).apply(sanitize_sms_text)
 
    # FECHA GESTION
    dt = df["DATE"].apply(parse_date_any)
    df["FECHA_GESTION_FMT"] = dt.dt.strftime("%d/%m/%Y %H:%M:%S")
 
    # Normalizar CEDULA para join
    df["CEDULA_JOIN"] = df["CUSTOMER_ID"].apply(clean_cedula_value)
 
    # Join con multicanal (traer NUMERO PRODUCTO)
    joined = df.merge(multicanal_map, left_on="CEDULA_JOIN", right_on="CEDULA", how="left")
    joined["NUMERO PRODUCTO"] = joined["NUMERO PRODUCTO"].fillna("").astype(str).str.strip()
 
    # Construcción salida
    out = pd.DataFrame({
        "CEDULA": joined["CEDULA_JOIN"],
        "NUMERO TELEFONO": joined["NUM_TELEPHONE_CLEAN"],
        "MENSAJE": joined["MENSAJE_TMP"],
        "ASESOR": CONSTANTES["ASESOR"],
        "FECHA GESTION": joined["FECHA_GESTION_FMT"],
        "CANAL": CONSTANTES["CANAL"],
        "ESTADO CLIENTE": CONSTANTES["ESTADO CLIENTE"],
        "ESTADO CONTACTO": CONSTANTES["ESTADO CONTACTO"],
        "NIVEL1": CONSTANTES["NIVEL1"],
        "NIVEL2": CONSTANTES["NIVEL2"],
        "NIVEL3": CONSTANTES["NIVEL3"],
        "NIVEL4": CONSTANTES["NIVEL4"],
        "NIVEL5": "",
        "NIVEL6": "",
        "NIVEL7": "",
        "NIVEL8": "",
        "NIVEL9": "",
        "NIVEL10": "",
        "NUMERO PRODUCTO": joined["NUMERO PRODUCTO"],
    })
 
    # Validaciones mínimas
    out = out.dropna(subset=["CEDULA", "NUMERO TELEFONO"]).copy()
    out["NUMERO TELEFONO"] = out["NUMERO TELEFONO"].astype("Int64")
 
    # Respetar orden del template
    tpl_cols = read_template_columns(template_path) if template_path.exists() else []
    final_cols = tpl_cols[:] if tpl_cols else FORMATO_COLUMNS
 
    for col in FORMATO_COLUMNS:
        if col not in final_cols:
            final_cols.append(col)
 
    final_cols = [c for c in final_cols if c and not str(c).lower().startswith("unnamed")]
 
    for col in final_cols:
        if col not in out.columns:
            out[col] = ""
 
    out.columns = [c.strip() if isinstance(c, str) else c for c in out.columns]
    out = out[final_cols].map(lambda v: v.strip() if isinstance(v, str) else v).fillna("")
    return out
 
# ========================= Main =========================
 
def main():
    load_dotenv()
    PREDICTIVO_DIR.mkdir(parents=True, exist_ok=True)
 
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"No existe el template: {TEMPLATE_PATH}")
 
    # 1) Multicanal local (último descargado)
    multicanal_file = pick_latest_local_csv(MULTICANAL_DIR)
    print(f"Usando Multicanal local: {multicanal_file}")
 
    df_multi = read_multicanal_local(multicanal_file)
    multicanal_map = build_multicanal_map(df_multi)
    print(f"Multicanal map (CEDULA únicos): {len(multicanal_map)}")
 
    # 2) Buscar automáticamente el CSV fuente generado por descarga_predictivo_sabado.py
    source_csv = find_wolkvox_source_csv(DATABRICKS_CSV_DIR)
    print(f"Usando Wolkvox CSV fuente: {source_csv}")
    df = read_wolkvox_csv(source_csv)
 
    # Asegurar columnas mínimas (por si faltan en algún envío)
    ensure_cols(df, ["opt1", "telephone", "result", "date", "customer_id"])
 
    # 3) Filtrar solo PROMOTORA (igual que antes)
    df = df[df["opt1"].astype(str).str.upper().eq("PROMOTORA")].copy()
 
    # 4) Si no hay datos, generar CSV vacío con headers del template
    if df.empty:
        print("No se encontraron registros para PROMOTORA en el CSV.")
        tpl_cols = read_template_columns(TEMPLATE_PATH)
        pd.DataFrame(columns=tpl_cols if tpl_cols else FORMATO_COLUMNS) \
            .to_csv(OUTPUT_FILE, index=False, encoding="utf-8", sep=";")
        print(f"CSV vacío -> {OUTPUT_FILE}")
        return
 
    # 5) Transformar a formato de cargue (con NUMERO PRODUCTO)
    out = build_cargue_from_df(df, TEMPLATE_PATH, multicanal_map)
 
    # 6) Guardar CSV final
    out.to_csv(OUTPUT_FILE, index=False, encoding="utf-8", sep=";")
 
    # 7) Log de control por RESULT (después del filtro)
    df_log = df.copy()
    df_log["result"] = df_log["result"].astype(str)
    df_log = df_log[~df_log["result"].str.upper().eq("ANSWER")]
    res_counts = df_log["result"].value_counts().rename_axis("RESULT").reset_index(name="COUNT")
 
    print(f"OK -> {OUTPUT_FILE}")
    print(f"Filas generadas: {len(out)}")
    if not res_counts.empty:
        print(res_counts.to_string(index=False))
 
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(2)