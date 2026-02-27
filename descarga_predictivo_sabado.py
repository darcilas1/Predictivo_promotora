import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from databricks import sql


# ========================= CONFIG =========================

load_dotenv()

PROJECT_ROOT  = Path(__file__).resolve().parent
PREDICTIVO_DIR = PROJECT_ROOT / "Predictivo"
PREDICTIVO_DIR.mkdir(parents=True, exist_ok=True)


def get_databricks_connection():
    """
    Crea una conexión al Databricks SQL Warehouse usando variables de entorno:
    SERVER_HOSTNAME, HTTP_PATH, ACCESS_TOKEN.
    """
    server_hostname = os.environ.get("SERVER_HOSTNAME")
    http_path       = os.environ.get("HTTP_PATH")
    access_token    = os.environ.get("ACCESS_TOKEN")

    if not all([server_hostname, http_path, access_token]):
        raise ValueError(
            "Faltan variables de entorno: SERVER_HOSTNAME, HTTP_PATH o ACCESS_TOKEN"
        )

    conn = sql.connect(
        server_hostname=server_hostname,
        http_path=http_path,
        access_token=access_token,
    )
    return conn


def export_query_to_csv(query: str, out_csv_path: Path) -> Path:
    """
    Ejecuta un query en Databricks SQL Warehouse y exporta el resultado a CSV.
    """
    conn = get_databricks_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            colnames = [c[0] for c in cur.description]
            rows = cur.fetchall()

        df = pd.DataFrame(rows, columns=colnames)
        df.to_csv(out_csv_path, index=False, encoding="utf-8")
        print(f"[OK] {len(df)} filas exportadas → {out_csv_path}")
        return out_csv_path
    finally:
        conn.close()


def main():
    # Fecha de hoy automática (Bogotá)
    try:
        from zoneinfo import ZoneInfo
        today = datetime.now(tz=ZoneInfo("America/Bogota")).date()
    except Exception:
        today = datetime.now().date()

    date_value       = today.strftime("%Y-%m-%d")
    opt1_value       = "PROMOTORA"
    excluded_result  = "ANSWER"

    print(f"[INFO] Descargando datos Wolkvox Databricks para fecha: {date_value}")

    query = f"""
    SELECT *
    FROM lakehouse.raw.wolkvox_campaign_3
    WHERE date(date) = '{date_value}'
      AND result <> '{excluded_result}'
      AND opt1 = '{opt1_value}'
      AND operacion = 'vg-lider-operacion4'
    """

    # Nombre de salida en la carpeta Predictivo/
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = f"wolkvox_campaign_3_{opt1_value}_{date_value}_{ts}.csv"
    out_path = PREDICTIVO_DIR / out_name

    export_query_to_csv(query=query, out_csv_path=out_path)
    print(f"CSV generado en: {out_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)