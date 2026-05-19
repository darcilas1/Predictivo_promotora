import os
import time
import glob
import shutil
from datetime import datetime, date
import pyotp

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, StaleElementReferenceException

from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError
from crm_navigation import (
    click_by_visible_text,
    click_campaign_detail_arrow,
    click_campaign_group_by_text,
    select_primefaces_option_by_text,
)

# =========================
# Carga de variables (.env)
# =========================
load_dotenv()

USERNAME_VG = os.getenv("USERNAME_VG")
PASSWORD_VG = os.getenv("PASSWORD_VG")
MFA_SECRET  = os.getenv("MFA_SECRET")

AWS_ACCESS_KEY_ID     = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION            = os.getenv("AWS_REGION")
S3_BUCKET             = os.getenv("S3_BUCKET")

S3_PREFIX_GESTIONES = "datos-vg/PROMOTORA/GESTIONES/"
S3_PREFIX_ACUERDOS  = "datos-vg/PROMOTORA/ACUERDOS/"

# =========================
# Paths locales
# =========================
BASE_DIR      = os.path.abspath(os.path.dirname(__file__))
DOWNLOAD_BASE = os.path.join(BASE_DIR, "downloads")
TMP_DOWNLOAD  = os.path.join(DOWNLOAD_BASE, "tmp")
GESTIONES_DIR = os.path.join(DOWNLOAD_BASE, "Gestiones")
ACUERDOS_DIR  = os.path.join(DOWNLOAD_BASE, "Acuerdos")

for p in [DOWNLOAD_BASE, TMP_DOWNLOAD, GESTIONES_DIR, ACUERDOS_DIR]:
    os.makedirs(p, exist_ok=True)

# =========================
# Zona horaria Bogotá
# =========================
def now_in_bogota():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(tz=ZoneInfo("America/Bogota"))
    except Exception:
        try:
            import pytz
            return datetime.now(tz=pytz.timezone("America/Bogota"))
        except Exception:
            return datetime.now()

# =========================
# Driver
# =========================
options = Options()
options.add_experimental_option("detach", True)
prefs = {
    "download.default_directory": TMP_DOWNLOAD,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True,
}
options.add_experimental_option("prefs", prefs)
driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, 20)

# =========================
# Utilidades generales
# =========================
def now_dt() -> date:
    return now_in_bogota().date()

def run_date_str() -> str:
    return now_in_bogota().strftime("%Y-%m-%d")

def _format_d_m_yy(d: date) -> str:
    """Formato para inputs de fecha en Iagree: 19/5/26"""
    return f"{d.day}/{d.month}/{d.year % 100:02d}"

def _add_ten_years(dt: date) -> date:
    try:
        return dt.replace(year=dt.year + 10)
    except ValueError:
        if dt.month == 2 and dt.day == 29:
            return date(dt.year + 10, 2, 28)
        raise

def today_iagree_str() -> str:
    """Formato de fecha que muestra la tabla de Iagree: 19/may/26"""
    months = {
        1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
        7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic"
    }
    dt = now_dt()
    return f"{dt.day:02d}/{months[dt.month]}/{dt.year % 100:02d}"

def normalize_cell_text(s: str) -> str:
    return " ".join((s or "").replace("\n", " ").split()).strip()

def wait_for_download_complete(download_dir: str, timeout: int = 600) -> str:
    end = time.time() + timeout
    last_path, last_size, stable = None, -1, 0
    while time.time() < end:
        if glob.glob(os.path.join(download_dir, "*.crdownload")):
            time.sleep(1)
            continue
        files = [f for f in glob.glob(os.path.join(download_dir, "*")) if os.path.isfile(f)]
        if not files:
            time.sleep(1)
            continue
        latest = max(files, key=os.path.getmtime)
        size   = os.path.getsize(latest)
        if latest == last_path and size == last_size:
            stable += 1
        else:
            stable = 0
            last_path, last_size = latest, size
        if stable >= 3:
            return latest
        time.sleep(1)
    raise TimeoutException("Timeout esperando la descarga del archivo.")

def get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
    )

def move_and_upload(local_src: str, target_dir: str, final_base: str, s3_prefix: str):
    final_name = f"{final_base}_{run_date_str()}.txt"
    final_path = os.path.join(target_dir, final_name)
    if os.path.exists(final_path):
        os.remove(final_path)
    shutil.move(local_src, final_path)
    s3_key = f"{s3_prefix}{final_name}"
    s3 = get_s3_client()
    try:
        s3.upload_file(final_path, S3_BUCKET, s3_key)
        print(f"[OK] Subido a s3://{S3_BUCKET}/{s3_key}")
        os.remove(final_path)
        print(f"[CLEANUP] Eliminado local: {final_path}")
    except ClientError as e:
        print(f"[ERROR] Falló subida a S3: {e}")
        print(f"[KEEP] Conservado local para reintento: {final_path}")

def safe_click(locator, desc: str = "", max_retries: int = 3):
    for attempt in range(1, max_retries + 1):
        try:
            el = wait.until(EC.element_to_be_clickable(locator))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
            time.sleep(0.5)
            el.click()
            if desc:
                print(f"[CLICK] {desc} (intento {attempt}) OK.")
            return
        except ElementClickInterceptedException:
            try:
                el = driver.find_element(*locator)
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", el)
                if desc:
                    print(f"[CLICK] {desc} con JS (intento {attempt}) OK.")
                return
            except ElementClickInterceptedException:
                continue
    raise

# =========================
# MFA Helper
# =========================
def ingresar_mfa(contexto: str = "login", max_reintentos: int = 3):
    """
    Ingresa el código TOTP con reintento automático.
    Criterio de éxito: el input del modal DESAPARECE (modal cerrado).
    Criterio de fallo: input sigue visible 5s después de Verificar.
    Caso B: si el modal ya no existe al iniciar el intento, toma como éxito.
    """
    input_xpath = '//input[contains(@placeholder,"000000") or contains(@placeholder,"0 0 0 0 0 0")]'
    boton_texto = "Verificar y entrar" if contexto == "login" else "Verificar y descargar"
    boton_xpath = f'//button[contains(., "{boton_texto}")]'
    totp        = pyotp.TOTP(MFA_SECRET)
    wait_corto  = WebDriverWait(driver, 5)

    for intento in range(1, max_reintentos + 1):
        # Caso B: modal ya desapareció durante la espera del ciclo anterior
        try:
            wait_corto.until(EC.visibility_of_element_located((By.XPATH, input_xpath)))
        except TimeoutException:
            print(f"[MFA] Modal ya no visible al inicio del intento {intento} — éxito.")
            return

        segundos_restantes = 30 - (int(time.time()) % 30)
        if segundos_restantes < 3:
            print(f"[MFA] Código por expirar en {segundos_restantes}s, esperando el siguiente...")
            time.sleep(segundos_restantes + 1)

        codigo = totp.now()
        segundos_restantes = 30 - (int(time.time()) % 30)
        print(f"[MFA] Intento {intento}/{max_reintentos} | contexto={contexto} | "
              f"código={codigo} | expira en {segundos_restantes}s")

        campo = wait.until(EC.element_to_be_clickable((By.XPATH, input_xpath)))
        campo.clear()
        campo.send_keys(codigo)
        time.sleep(0.5)
        wait.until(EC.element_to_be_clickable((By.XPATH, boton_xpath))).click()

        try:
            wait_corto.until(EC.invisibility_of_element_located((By.XPATH, input_xpath)))
            print(f"[MFA] ✓ Código {contexto} verificado correctamente (intento {intento}).")
            return
        except TimeoutException:
            print(f"[MFA] ⚠ Código rechazado (modal sigue visible) en intento {intento}. "
                  "Esperando próximo ciclo de 30s...")
            tiempo_espera = 30 - (int(time.time()) % 30) + 1
            time.sleep(tiempo_espera)

    raise RuntimeError(
        f"[MFA] ✗ Falló la verificación MFA tras {max_reintentos} intentos ({contexto}). "
        "Revisa el MFA_SECRET en el .env o el estado de Iagree."
    )

# =========================
# Helpers S3
# =========================
def archivo_existe_en_s3(s3_prefix: str, final_base: str) -> bool:
    """
    Verifica si el archivo de hoy ya existe en S3.
    Nombre esperado: {final_base}_{YYYY-MM-DD}.txt
    """
    s3_key = f"{s3_prefix}{final_base}_{run_date_str()}.txt"
    s3 = get_s3_client()
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
        print(f"[S3] Archivo ya existe: s3://{S3_BUCKET}/{s3_key}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            print(f"[S3] Archivo NO existe: s3://{S3_BUCKET}/{s3_key}")
            return False
        raise

# =========================
# Helpers tabla Iagree
# =========================
def _get_tabla_rows(n_filas: int = 2):
    """
    Retorna las primeras n_filas de la tabla del histórico de descargas.
    Busca la tabla por encabezado 'Informe' para no depender de IDs dinámicos.
    """
    rows = []
    for i in range(1, n_filas + 1):
        xp = f'//table[.//th[contains(.,"Informe")]]//tbody/tr[{i}]'
        try:
            row = wait.until(EC.presence_of_element_located((By.XPATH, xp)))
            rows.append(row)
        except TimeoutException:
            break
    return rows

def _get_cell(row, col_index: int) -> str:
    """Retorna el texto de la celda col_index (1-based) de una fila."""
    try:
        cell = row.find_element(By.XPATH, f"td[{col_index}]")
        return normalize_cell_text(cell.text)
    except Exception:
        return ""

def _get_col_index(header_text: str) -> int:
    """Índice (1-based) de la columna por encabezado. Robusto ante IDs dinámicos."""
    headers = driver.find_elements(
        By.XPATH, '//table[.//th[contains(.,"Informe")]]//th'
    )
    for i, th in enumerate(headers, start=1):
        try:
            if header_text.casefold() in normalize_cell_text(th.text).casefold():
                return i
        except StaleElementReferenceException:
            continue
    raise ValueError(f"Columna '{header_text}' no encontrada en la tabla")

def _click_download_button_in_row(row_index: int, desc: str = ""):
    """
    Hace clic en el botón de descarga de la fila row_index (1-based) de la tabla.
    Este botón NO pide MFA porque es una descarga de un informe ya generado.
    """
    # El botón de descarga es el último elemento clickeable de la fila (ícono de descarga)
    btn_xpath = (
        f'//table[.//th[contains(.,"Informe")]]//tbody/tr[{row_index}]'
        f'//button[contains(@class,"ui-button") and not(contains(@class,"ui-state-disabled"))]'
        f' | '
        f'//table[.//th[contains(.,"Informe")]]//tbody/tr[{row_index}]//td[last()]//button'
    )
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, btn_xpath)))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.3)
        btn.click()
        print(f"[CLICK] Botón descarga fila {row_index} ({desc}) OK — sin MFA.")
    except Exception as e:
        # Fallback: JS click
        try:
            driver.execute_script("arguments[0].click();", btn)
            print(f"[CLICK] Botón descarga fila {row_index} ({desc}) con JS OK.")
        except Exception:
            raise RuntimeError(f"No se pudo hacer clic en botón descarga fila {row_index}: {e}")

# =========================
# Lógica de 3 niveles — Gestión Universo
# =========================
def manejar_gestiones() -> bool:
    """
    Nivel 1: ¿Ya está en S3?          → omitir
    Nivel 2: ¿Está en tabla (fila 1-2) con fechas correctas?
                                       → descargar desde tabla (sin MFA)
    Nivel 3: Generar desde cero        → con MFA

    Retorna True si se descargó/subió correctamente, False si ya estaba en S3.
    """
    today        = now_dt()
    today_str    = today_iagree_str()          # ej: 19/may/26
    final_base   = "Gestiones_Promotora"

    # ── Nivel 1: verificar S3 ──
    if archivo_existe_en_s3(S3_PREFIX_GESTIONES, final_base):
        print("[GESTIONES] Archivo ya en S3 — omitiendo.")
        return False

    # ── Nivel 2: buscar en primeras 2 filas de la tabla ──
    print("[GESTIONES] Buscando en tabla Iagree (primeras 2 filas)...")
    select_primefaces_option_by_text(driver, "Seleccione Uno", "Gestión Universo")
    time.sleep(1)

    try:
        col_informe  = _get_col_index("Informe")
        col_fecha_d  = _get_col_index("Fecha Descarga")
        col_cond_ini = _get_col_index("Cond. Inicial")
        col_cond_fin = _get_col_index("Cond. Final")
    except ValueError as e:
        print(f"[WARN] {e} — usando posiciones por defecto (1,3,4,5).")
        col_informe, col_fecha_d, col_cond_ini, col_cond_fin = 1, 3, 4, 5

    fila_encontrada = None
    rows = _get_tabla_rows(n_filas=2)
    for idx, row in enumerate(rows, start=1):
        try:
            informe_txt  = _get_cell(row, col_informe)
            fecha_d_txt  = _get_cell(row, col_fecha_d)   # ej: "19/may/26 02:12 PM"
            cond_ini_txt = _get_cell(row, col_cond_ini)  # ej: "19/may/26"
            cond_fin_txt = _get_cell(row, col_cond_fin)  # ej: "19/may/26"

            ok_informe  = informe_txt.casefold() == "gestión universo".casefold()
            # Fecha Descarga contiene la hora; verificamos que empiece con la fecha de hoy
            ok_fecha_d  = fecha_d_txt.casefold().startswith(today_str.casefold())
            ok_cond_ini = cond_ini_txt.casefold() == today_str.casefold()
            ok_cond_fin = cond_fin_txt.casefold() == today_str.casefold()

            print(f"[GESTIONES] Fila {idx}: informe='{informe_txt}' | "
                  f"fecha_desc='{fecha_d_txt}' | cond_ini='{cond_ini_txt}' | cond_fin='{cond_fin_txt}'")

            if ok_informe and ok_fecha_d and ok_cond_ini and ok_cond_fin:
                fila_encontrada = idx
                print(f"[GESTIONES] ✓ Fila {idx} cumple condiciones — descargando desde tabla.")
                break
        except StaleElementReferenceException:
            print(f"[WARN] Fila {idx} stale, saltando...")
            continue

    if fila_encontrada:
        # Descarga desde la fila encontrada — NO pide MFA
        _click_download_button_in_row(fila_encontrada, "Gestión Universo desde tabla")
        file_gestion = wait_for_download_complete(TMP_DOWNLOAD, timeout=600)
        move_and_upload(file_gestion, GESTIONES_DIR, final_base, S3_PREFIX_GESTIONES)
        return True

    # ── Nivel 3: generar desde cero ──
    print("[GESTIONES] No encontrado en tabla — generando desde cero (con MFA)...")
    # Ya estamos en Gestión Universo (se seleccionó arriba), ponemos las fechas
    fecha_hoy = _format_d_m_yy(today)
    time.sleep(1)
    wait.until(EC.element_to_be_clickable(
        (By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechDesde_input"]')
    )).send_keys(fecha_hoy)
    time.sleep(1)
    wait.until(EC.element_to_be_clickable(
        (By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechasta_input"]')
    )).send_keys(fecha_hoy)

    wait.until(EC.element_to_be_clickable(
        (By.XPATH, '//*[@id="mainForm:pgMenuExportacion:btnDownload"]/span[2]')
    )).click()

    ingresar_mfa(contexto="descarga")

    file_gestion = wait_for_download_complete(TMP_DOWNLOAD, timeout=600)
    move_and_upload(file_gestion, GESTIONES_DIR, final_base, S3_PREFIX_GESTIONES)
    return True

# =========================
# Lógica de 3 niveles — Matriz de Acuerdos
# =========================
def manejar_acuerdos() -> bool:
    """
    Nivel 1: ¿Ya está en S3?          → omitir
    Nivel 2: ¿Está en tabla (fila 1-2) con fechas correctas?
                                       → descargar desde tabla (sin MFA)
    Nivel 3: Generar desde cero        → con MFA

    Fechas esperadas para Acuerdos:
      Cond. Inicial = primer día del mes actual  (ej: 01/may/26)
      Cond. Final   = primer día del mes + 10 años (ej: 01/may/36)

    Retorna True si se descargó/subió correctamente, False si ya estaba en S3.
    """
    today          = now_dt()
    primer_dia_mes = date(today.year, today.month, 1)
    fecha_fin_dt   = _add_ten_years(primer_dia_mes)
    final_base     = "Acuerdos_Promotora"

    months = {
        1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
        7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic"
    }
    def _to_iagree_fmt(d: date) -> str:
        return f"{d.day:02d}/{months[d.month]}/{d.year % 100:02d}"

    expected_cond_ini = _to_iagree_fmt(primer_dia_mes)   # ej: 01/may/26
    expected_cond_fin = _to_iagree_fmt(fecha_fin_dt)     # ej: 01/may/36
    today_str         = today_iagree_str()               # ej: 19/may/26 (para Fecha Descarga)

    # ── Nivel 1: verificar S3 ──
    if archivo_existe_en_s3(S3_PREFIX_ACUERDOS, final_base):
        print("[ACUERDOS] Archivo ya en S3 — omitiendo.")
        return False

    # ── Nivel 2: buscar en primeras 2 filas de la tabla ──
    print("[ACUERDOS] Buscando en tabla Iagree (primeras 2 filas)...")
    time.sleep(2)
    select_primefaces_option_by_text(driver, "Seleccione Uno", "Informe Matriz Acuerdos")
    time.sleep(1)

    try:
        col_informe  = _get_col_index("Informe")
        col_fecha_d  = _get_col_index("Fecha Descarga")
        col_cond_ini = _get_col_index("Cond. Inicial")
        col_cond_fin = _get_col_index("Cond. Final")
    except ValueError as e:
        print(f"[WARN] {e} — usando posiciones por defecto (1,3,4,5).")
        col_informe, col_fecha_d, col_cond_ini, col_cond_fin = 1, 3, 4, 5

    fila_encontrada = None
    rows = _get_tabla_rows(n_filas=2)
    for idx, row in enumerate(rows, start=1):
        try:
            informe_txt  = _get_cell(row, col_informe)
            fecha_d_txt  = _get_cell(row, col_fecha_d)
            cond_ini_txt = _get_cell(row, col_cond_ini)
            cond_fin_txt = _get_cell(row, col_cond_fin)

            ok_informe  = informe_txt.casefold() == "informe matriz acuerdos".casefold()
            ok_fecha_d  = fecha_d_txt.casefold().startswith(today_str.casefold())
            ok_cond_ini = cond_ini_txt.casefold() == expected_cond_ini.casefold()
            ok_cond_fin = cond_fin_txt.casefold() == expected_cond_fin.casefold()

            print(f"[ACUERDOS] Fila {idx}: informe='{informe_txt}' | "
                  f"fecha_desc='{fecha_d_txt}' | cond_ini='{cond_ini_txt}' | cond_fin='{cond_fin_txt}'")
            print(f"           Esperado: cond_ini='{expected_cond_ini}' | cond_fin='{expected_cond_fin}'")

            if ok_informe and ok_fecha_d and ok_cond_ini and ok_cond_fin:
                fila_encontrada = idx
                print(f"[ACUERDOS] ✓ Fila {idx} cumple condiciones — descargando desde tabla.")
                break
        except StaleElementReferenceException:
            print(f"[WARN] Fila {idx} stale, saltando...")
            continue

    if fila_encontrada:
        # Descarga desde la fila encontrada — NO pide MFA
        _click_download_button_in_row(fila_encontrada, "Informe Matriz Acuerdos desde tabla")
        file_acuerdo = wait_for_download_complete(TMP_DOWNLOAD, timeout=600)
        move_and_upload(file_acuerdo, ACUERDOS_DIR, final_base, S3_PREFIX_ACUERDOS)
        return True

    # ── Nivel 3: generar desde cero ──
    print("[ACUERDOS] No encontrado en tabla — generando desde cero (con MFA)...")
    fecha_inicio = _format_d_m_yy(primer_dia_mes)
    fecha_fin    = _format_d_m_yy(fecha_fin_dt)

    time.sleep(1)
    wait.until(EC.element_to_be_clickable(
        (By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechDesde_input"]')
    )).clear()
    time.sleep(1)
    wait.until(EC.element_to_be_clickable(
        (By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechDesde_input"]')
    )).send_keys(fecha_inicio)
    time.sleep(1)
    wait.until(EC.element_to_be_clickable(
        (By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechasta_input"]')
    )).clear()
    time.sleep(1)
    wait.until(EC.element_to_be_clickable(
        (By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechasta_input"]')
    )).send_keys(fecha_fin)

    wait.until(EC.element_to_be_clickable(
        (By.XPATH, '//*[@id="mainForm:pgMenuExportacion:btnDownload"]/span[2]')
    )).click()

    ingresar_mfa(contexto="descarga")

    file_acuerdo = wait_for_download_complete(TMP_DOWNLOAD, timeout=600)
    move_and_upload(file_acuerdo, ACUERDOS_DIR, final_base, S3_PREFIX_ACUERDOS)
    return True

# =========================
# Flujo principal
# =========================
driver.get('https://visiong.iagree.co/iAgree/faces/login.xhtml')
driver.maximize_window()
time.sleep(3)

# --- Login ---
XP_USUARIO    = '//input[@placeholder="Usuario" or contains(@placeholder,"suario")]'
XP_PASSWORD   = '//input[@placeholder="Contraseña" or @type="password"]'
XP_CAPTCHA_IN = '//input[contains(@placeholder,"aptcha") or contains(@placeholder,"APTCHA")]'

wait.until(EC.presence_of_element_located((By.XPATH, XP_USUARIO)))
time.sleep(3)
driver.find_element(By.XPATH, XP_USUARIO).send_keys(USERNAME_VG)
driver.find_element(By.XPATH, XP_PASSWORD).send_keys(PASSWORD_VG)
time.sleep(2)

captcha_valor = driver.find_element(By.ID, "captcha").text.strip()
captcha_input = driver.find_element(By.XPATH, XP_CAPTCHA_IN)
captcha_input.send_keys(captcha_valor)
captcha_input.send_keys(Keys.RETURN)

# --- MFA Login ---
ingresar_mfa(contexto="login")

# --- Selección de campaña ---
click_campaign_group_by_text(driver)
time.sleep(1)
click_campaign_detail_arrow(driver)

# --- Navegación a Informes ---
click_by_visible_text(driver, ["Exportar", "Exportaciones"], desc="Menú Exportar")
time.sleep(0.5)
click_by_visible_text(driver, "Informes", desc="Submenú Informes")

# ============ Gestión Universo — lógica 3 niveles ============
descargo_gestiones = manejar_gestiones()
if not descargo_gestiones:
    print("[INFO] Gestiones ya estaba en S3, se omitió.")

# ============ Matriz de Acuerdos — lógica 3 niveles ============
descargo_acuerdos = manejar_acuerdos()
if not descargo_acuerdos:
    print("[INFO] Acuerdos ya estaba en S3, se omitió.")

if not descargo_gestiones and not descargo_acuerdos:
    print("[DONE] Ambos archivos ya estaban en S3. No se descargó nada.")
else:
    print("[DONE] Proceso de contingencia finalizado.")

driver.quit()