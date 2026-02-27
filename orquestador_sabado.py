import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

import requests
from dotenv import load_dotenv

# ========================= CONFIG =========================

load_dotenv()

BASE_DIR   = Path(__file__).resolve().parent
python_exe = sys.executable  # Usa el Python del venv activo

# ----------------------------------------------------------
# Secuencia del proceso SÁBADO:
#   1. descarga_predictivo_sabado.py  → Descarga datos de Databricks
#   2. predictivo_sabado.py           → Prepara el CSV de cargue
#   3. RPA_Cargue.py                  → Carga al CRM
# Si cualquier proceso falla, se abortan los siguientes.
# ----------------------------------------------------------

PROCESOS = [
    ("Descarga Predictivo Databricks", BASE_DIR / "descarga_predictivo_sabado.py"),
    ("Preparación Predictivo Sábado",  BASE_DIR / "predictivo_sabado.py"),
    ("Cargue Promotora",               BASE_DIR / "RPA_Cargue.py"),
]

# Logs
LOGS_DIR = BASE_DIR / "logs_orquestador"
LOGS_DIR.mkdir(exist_ok=True)

TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL")

# ========================= LOGGING =========================

def log(msg: str):
    """Escribe log en consola y en archivo de log diario."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)

    log_file = LOGS_DIR / f"orquestador_sabado_{datetime.now().strftime('%Y%m%d')}.log"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ========================= TEAMS =========================

def notificar_teams_resumen(exitosos: list, fallidos: list, no_ejecutados: list):
    """Envía a Teams el resumen final de la ejecución del sábado."""
    if not TEAMS_WEBHOOK_URL:
        log("⚠ TEAMS_WEBHOOK_URL no configurado. No se enviará resumen a Teams.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(exitosos) + len(fallidos) + len(no_ejecutados)

    lineas = [
        "📊 *Resumen de ejecución RPA – PROMOTORA PREDICTIVO SÁBADO*",
        "",
        f"**Fecha/Hora:** {timestamp}",
        f"**Total procesos:** {total}",
        f"**Exitosos:** {len(exitosos)}",
        f"**Fallidos / Detenidos:** {len(fallidos) + len(no_ejecutados)}",
        "",
    ]

    if exitosos:
        lineas.append("✅ **Procesos exitosos:**")
        lineas.append("\n".join(f"- {n}" for n in exitosos))
        lineas.append("")

    if fallidos:
        lineas.append("❌ **Procesos fallidos:**")
        lineas.append("\n".join(f"- {n}" for n in fallidos))
        lineas.append("")

    if no_ejecutados:
        lineas.append("⏭ **No ejecutados (abortados por fallo previo):**")
        lineas.append("\n".join(f"- {n}" for n in no_ejecutados))
        lineas.append("")

    if fallidos or no_ejecutados:
        lineas.append("_Revisar logs locales del orquestador para más detalle._")

    payload = {"text": "\n".join(lineas)}
    try:
        resp = requests.post(TEAMS_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code != 200:
            log(f"❌ Error al enviar resumen a Teams. Status: {resp.status_code}")
        else:
            log("📨 Resumen final enviado a Teams exitosamente.")
    except requests.RequestException as e:
        log(f"❌ Excepción al enviar resumen a Teams: {e}")


# ========================= EJECUCIÓN =========================

def ejecutar_proceso(nombre: str, ruta: Path) -> bool:
    """
    Ejecuta un script Python como subprocess.
    Devuelve True si terminó con código 0, False en caso contrario.
    """
    log(f"▶ Iniciando proceso: {nombre} ({ruta.name})")

    if not ruta.exists():
        log(f"❌ ERROR: el archivo no existe: {ruta}")
        return False

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [python_exe, str(ruta)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )

    if result.returncode != 0:
        log(f"❌ ERROR en '{nombre}'. Código de salida: {result.returncode}")
        if result.stderr:
            log(f"   STDERR:\n{result.stderr}")
        if result.stdout:
            log(f"   STDOUT:\n{result.stdout}")
        return False

    log(f"✅ Proceso '{nombre}' finalizado correctamente.")
    if result.stdout:
        log(f"   STDOUT:\n{result.stdout}")
    return True


# ========================= MAIN =========================

def main():
    log("=" * 65)
    log("🚀 Iniciando Orquestador RPA SÁBADO – PROMOTORA PREDICTIVO")
    log("=" * 65)

    exitosos: list      = []
    fallidos: list      = []
    no_ejecutados: list = []

    fallo = False

    for nombre, ruta in PROCESOS:
        if fallo:
            no_ejecutados.append(nombre)
            log(f"⏭ Proceso omitido (fallo previo): {nombre}")
            continue

        ok = ejecutar_proceso(nombre, ruta)
        if ok:
            exitosos.append(nombre)
        else:
            fallidos.append(nombre)
            fallo = True
            log(f"⚠ Proceso fallido: '{nombre}'. Abortando ejecución...")

    # ── RESUMEN FINAL ──
    log("\n" + "=" * 65)
    log("📊 RESUMEN FINAL DE EJECUCIÓN SÁBADO")
    log("=" * 65)
    log(f"   ✅ Exitosos       ({len(exitosos)}): {', '.join(exitosos) if exitosos else 'Ninguno'}")
    log(f"   ❌ Fallidos       ({len(fallidos)}): {', '.join(fallidos) if fallidos else 'Ninguno'}")
    log(f"   ⏭  No ejecutados  ({len(no_ejecutados)}): {', '.join(no_ejecutados) if no_ejecutados else 'Ninguno'}")
    log("=" * 65)

    notificar_teams_resumen(exitosos, fallidos, no_ejecutados)


if __name__ == "__main__":
    main()
