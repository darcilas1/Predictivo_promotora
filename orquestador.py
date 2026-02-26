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

BASE_DIR = Path(__file__).resolve().parent
python_exe = sys.executable  # Usa el Python del venv activo

# ----------------------------------------------------------
# Secuencia de ejecución:
#   1. RPA_descargue_multicanal.py  ← No aborta si falla
#   2. main_predictivo.py           ← Aborta cadena si falla
#   3. RPA_Cargue.py                ← Aborta cadena si falla
#   4. [ESPERA 5 min]   → descargue_gestiones_acuerdos.py
#   5. [ESPERA 40 min]  → contingencia_descargue_ges_ac.py
# ----------------------------------------------------------

# Primer proceso: siempre se ejecuta, su fallo NO aborta la cadena
PROCESO_MULTICANAL = ("Descargue Multicanal", BASE_DIR / "RPA_descargue_multicanal.py")

# Procesos encadenados: si cualquiera falla, se abortan los siguientes
PROCESOS_ENCADENADOS = [
    ("Procesamiento Predictivo", BASE_DIR / "main_predictivo.py"),
    ("Cargue Promotora",         BASE_DIR / "RPA_Cargue.py"),
]

# Esperas y procesos posteriores
ESPERA_ANTES_DESCARGUE_GESTIONES = 5 * 60       # 5 minutos en segundos
ESPERA_ANTES_CONTINGENCIA        = 40 * 60      # 40 minutos en segundos

PROCESO_DESCARGUE_GESTIONES = ("Descargue Gestiones y Acuerdos", BASE_DIR / "descargue_gestiones_acuerdos.py")
PROCESO_CONTINGENCIA        = ("Contingencia Descargue Gest./Ac.", BASE_DIR / "contingencia_descargue_ges_ac.py")

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

    log_file = LOGS_DIR / f"orquestador_{datetime.now().strftime('%Y%m%d')}.log"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_espera(segundos: int, motivo: str):
    """Muestra un countdown cada minuto mientras espera."""
    log(f"⏳ Esperando {segundos // 60} minuto(s) antes de: {motivo}")
    restantes = segundos
    while restantes > 0:
        time.sleep(min(60, restantes))
        restantes -= 60
        if restantes > 0:
            log(f"   ⏱  Faltan {restantes // 60} min {restantes % 60} seg para: {motivo}")
    log(f"✅ Espera finalizada. Iniciando: {motivo}")


# ========================= TEAMS =========================

def notificar_teams_resumen(exitosos: list, fallidos: list, no_ejecutados: list):
    """Envía a Teams el resumen final de toda la ejecución."""
    if not TEAMS_WEBHOOK_URL:
        log("⚠ TEAMS_WEBHOOK_URL no configurado. No se enviará resumen final a Teams.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(exitosos) + len(fallidos) + len(no_ejecutados)

    lineas = [
        "📊 *Resumen de ejecución RPA – PROMOTORA PREDICTIVO*",
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
    log("🚀 Iniciando Orquestador RPA – PROMOTORA PREDICTIVO")
    log("=" * 65)

    exitosos: list = []
    fallidos: list = []
    no_ejecutados: list = []

    # ── FASE 1a: Descargue Multicanal (siempre corre, no aborta si falla) ──
    log("\n📋 FASE 1: Descargue Multicanal (no bloquea si falla)")
    nombre_mc, ruta_mc = PROCESO_MULTICANAL
    ok_mc = ejecutar_proceso(nombre_mc, ruta_mc)
    if ok_mc:
        exitosos.append(nombre_mc)
    else:
        fallidos.append(nombre_mc)
        log(f"⚠ '{nombre_mc}' falló, pero se continúa con los siguientes procesos.")

    # ── FASE 1b: Procesos encadenados (abortan si cualquiera falla) ──
    log("\n📋 FASE 1b: Procesos encadenados")
    fallo_principal = False

    for nombre, ruta in PROCESOS_ENCADENADOS:
        if fallo_principal:
            no_ejecutados.append(nombre)
            log(f"⏭ Proceso omitido (fallo previo): {nombre}")
            continue

        ok = ejecutar_proceso(nombre, ruta)
        if ok:
            exitosos.append(nombre)
        else:
            fallidos.append(nombre)
            fallo_principal = True
            log(f"⚠ Proceso fallido: '{nombre}'. Abortando fase principal...")


    # ── FASE 2: Descargue Gestiones y Acuerdos (con espera previa de 5 min) ──
    nombre_gest, ruta_gest = PROCESO_DESCARGUE_GESTIONES
    if fallo_principal:
        # Si la fase 1 falló, también omitimos las fases 2 y 3
        no_ejecutados.append(nombre_gest)
        no_ejecutados.append(PROCESO_CONTINGENCIA[0])
        log(f"\n⏭ FASE 2 y 3 omitidas por fallo en fase principal.")
    else:
        log(f"\n📋 FASE 2: {nombre_gest} (espera previa de 5 min)")
        log_espera(ESPERA_ANTES_DESCARGUE_GESTIONES, nombre_gest)

        ok_gest = ejecutar_proceso(nombre_gest, ruta_gest)
        if ok_gest:
            exitosos.append(nombre_gest)
        else:
            fallidos.append(nombre_gest)

        # ── FASE 3: Contingencia (con espera previa de 40 min, independiente del fallo de fase 2) ──
        nombre_cont, ruta_cont = PROCESO_CONTINGENCIA
        log(f"\n📋 FASE 3: {nombre_cont} (espera previa de 40 min)")
        log_espera(ESPERA_ANTES_CONTINGENCIA, nombre_cont)

        ok_cont = ejecutar_proceso(nombre_cont, ruta_cont)
        if ok_cont:
            exitosos.append(nombre_cont)
        else:
            fallidos.append(nombre_cont)

    # ── RESUMEN FINAL ──
    log("\n" + "=" * 65)
    log("📊 RESUMEN FINAL DE EJECUCIÓN")
    log("=" * 65)
    log(f"   ✅ Exitosos       ({len(exitosos)}): {', '.join(exitosos) if exitosos else 'Ninguno'}")
    log(f"   ❌ Fallidos       ({len(fallidos)}): {', '.join(fallidos) if fallidos else 'Ninguno'}")
    log(f"   ⏭  No ejecutados  ({len(no_ejecutados)}): {', '.join(no_ejecutados) if no_ejecutados else 'Ninguno'}")
    log("=" * 65)

    notificar_teams_resumen(exitosos, fallidos, no_ejecutados)


if __name__ == "__main__":
    main()
