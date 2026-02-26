import os
import time
import glob
import shutil
from datetime import datetime, date
 
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException

from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError
 
# =========================
# Carga de variables (.env)
# =========================
load_dotenv()
 
# Credenciales del portal
USERNAME_VG = os.getenv("USERNAME_VG")
PASSWORD_VG = os.getenv("PASSWORD_VG")
 
# AWS
AWS_ACCESS_KEY_ID     = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION            = os.getenv("AWS_REGION")
S3_BUCKET             = os.getenv("S3_BUCKET")
 
# Prefijos S3 por tipo
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
# Driver (descarga forzada)
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
# Utilidades
# =========================
def wait_for_download_complete(download_dir: str, timeout: int = 600) -> str:
    """
    Espera a que no haya .crdownload y el archivo esté estable (3 lecturas seguidas).
    Retorna la ruta del archivo descargado.
    """
    end = time.time() + timeout
    last_path, last_size, stable = None, -1, 0
 
    while time.time() < end:
        # si hay archivos en progreso, espera
        if glob.glob(os.path.join(download_dir, "*.crdownload")):
            time.sleep(1)
            continue
 
        files = [f for f in glob.glob(os.path.join(download_dir, "*")) if os.path.isfile(f)]
        if not files:
            time.sleep(1)
            continue
 
        latest = max(files, key=os.path.getmtime)
        size = os.path.getsize(latest)
 
        if latest == last_path and size == last_size:
            stable += 1
        else:
            stable = 0
            last_path, last_size = latest, size
 
        if stable >= 3:
            return latest
 
        time.sleep(1)
 
    raise TimeoutException("Timeout esperando la descarga del archivo.")
 
def run_date_str():
    """Fecha actual (Bogotá) en formato YYYY-MM-DD para el nombre final."""
    return now_in_bogota().strftime("%Y-%m-%d")
 
def get_s3_client():
    """
    Crea el cliente S3 con credenciales del .env
    """
    return boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION
    )
 
def move_and_upload(local_src: str, target_dir: str, final_base: str, s3_prefix: str):
    """
    Mueve el archivo descargado a target_dir con nombre final exacto y lo sube a S3.
    final_base: 'Gestiones_Promotora' | 'Acuerdos_Promotora'
    Nombre final: {final_base}_{YYYY-MM-DD}.txt
    Tras SUBIDA EXITOSA: elimina el archivo local.
    """
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
    """
    Hace click en un elemento de forma robusta:
    - Espera a que sea clickable
    - Hace scroll al centro
    - Intenta click normal
    - Si es interceptado, reintenta usando JS click
    """
    for attempt in range(1, max_retries + 1):
        try:
            el = wait.until(EC.element_to_be_clickable(locator))
            # Scroll al centro de la pantalla
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
            time.sleep(0.5)
            el.click()
            if desc:
                print(f"[CLICK] {desc} (intento {attempt}) OK.")
            return
        except ElementClickInterceptedException:
            print(f"[WARN] Click interceptado en {desc or locator} (intento {attempt}). "
                  "Reintentando con JS click...")
            try:
                el = driver.find_element(*locator)
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", el)
                if desc:
                    print(f"[CLICK] {desc} con JS (intento {attempt}) OK.")
                return
            except ElementClickInterceptedException:
                # último intento en el siguiente loop
                continue

    # Si llegó aquí, fallaron todos los intentos
    raise

# =========================
# Verificaciones para Gestión Universo
# =========================
def today_iagree_str() -> str:
    """
    Devuelve la fecha de hoy (Bogotá) con el formato que muestra la tabla: 01/ene/26
    """
    months = {
        1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
        7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic"
    }
    dt = now_in_bogota().date()
    dd = f"{dt.day:02d}"
    mmm = months[dt.month]
    yy = f"{dt.year % 100:02d}"
    return f"{dd}/{mmm}/{yy}"
 
def normalize_cell_text(s: str) -> str:
    return " ".join((s or "").replace("\n", " ").split()).strip()
 
def should_download_gestion_universo() -> bool:
    """
    Valida fila 1:
    - Informe == 'Gestión Universo'
    - Cond. Inicial (td[3]) == fecha de hoy en formato 01/ene/26
    - Cond. Inicial (td[4]) == fecha de hoy en formato 01/ene/26
    """
    expected_date = today_iagree_str()
 
    xp_informe = '//*[@id="mainForm:pgMenuExportacion:j_idt242_data"]/tr[1]/td[1]'
    xp_cond1   = '//*[@id="mainForm:pgMenuExportacion:j_idt242_data"]/tr[1]/td[3]'
    xp_cond2   = '//*[@id="mainForm:pgMenuExportacion:j_idt242_data"]/tr[1]/td[4]'
 
    informe_txt = normalize_cell_text(wait.until(EC.presence_of_element_located((By.XPATH, xp_informe))).text)
    cond1_txt   = normalize_cell_text(wait.until(EC.presence_of_element_located((By.XPATH, xp_cond1))).text)
    cond2_txt   = normalize_cell_text(wait.until(EC.presence_of_element_located((By.XPATH, xp_cond2))).text)
 
    ok_informe = informe_txt.casefold() == "gestión universo".casefold()
    ok_cond1 = cond1_txt == expected_date
    ok_cond2 = cond2_txt == expected_date
 
    if not ok_informe or not ok_cond1 or not ok_cond2:
        print("[SKIP] No se descarga Gestión Universo: validación no cumple.")
        print(f"       Informe (esperado 'Gestión Universo'): '{informe_txt}'")
        print(f"       Cond1   (esperado '{expected_date}'): '{cond1_txt}'")
        print(f"       Cond2   (esperado '{expected_date}'): '{cond2_txt}'")
        return False
 
    print(f"[OK] Validación Gestión Universo correcta (Informe y fechas = {expected_date}).")
    return True
 
# =========================
# Flujo
# =========================
driver.get('https://visiong.iagree.co/iAgree/faces/login.xhtml')
driver.maximize_window()
 
# --- Login ---
wait.until(EC.presence_of_element_located((By.NAME, "loginForm:j_idt22")))
driver.find_element(By.NAME, "loginForm:j_idt22").send_keys(USERNAME_VG)
driver.find_element(By.NAME, "loginForm:j_idt24").send_keys(PASSWORD_VG)
time.sleep(2)
 
captcha_text = driver.find_element(By.ID, "captcha")
captcha_input = driver.find_element(By.NAME, "loginForm:j_idt26")
captcha_input.send_keys(captcha_text.text)
captcha_input.send_keys(Keys.RETURN)
 
# --- Selección de campaña ---
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:dtGrupoCampanas_data"]/tr[20]')))
time.sleep(1)
driver.find_element(By.XPATH, '//*[@id="mainForm:dtGrupoCampanas_data"]/tr[20]').click()
 
select_promotora_octubre = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:dtCampanas:0:j_idt204"]')))
time.sleep(1)
select_promotora_octubre.click()
 
# --- Navegación a Informes (usa safe_click) ---
safe_click((By.XPATH, '//*[@id="mainForm:j_idt625"]/a'), desc="Menú Exportaciones")
time.sleep(0.5)
safe_click((By.XPATH, '//*[@id="mainForm:mnInformes"]/a'), desc="Submenú Informes")
 
# ============ 1) Gestión universo ============
# Antes: click directo al botón.
# Ahora: primero valida fila 1 (Informe + Cond Iniciales con fecha de hoy).
if should_download_gestion_universo():
    wait.until(EC.element_to_be_clickable((
        By.XPATH,
        '/html/body/div[1]/form/div[2]/div[2]/div/div[1]/div/div[1]/div/div/div/div/span[2]/span/div/div/div/div[3]/table/tbody/tr[1]/td[7]/button'
    ))).click()
 
    file_gestion = wait_for_download_complete(TMP_DOWNLOAD, timeout=600)
    move_and_upload(
        file_gestion,
        GESTIONES_DIR,
        final_base="Gestiones_Promotora",
        s3_prefix=S3_PREFIX_GESTIONES
    )
else:
    print("[INFO] Gestión Universo no descargada ni subida a S3 (ya existe / no corresponde a hoy).")
 
# ============ 2) Matriz de acuerdos ============
time.sleep(2)
type_info_generation = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:tipInfo_label"]')))
type_info_generation.click()
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:tipInfo_13"]'))).click()
 
# Rango de fechas para acuerdos (tu lógica actual)
def _format_d_m_yy(d: date) -> str:
    return f"{d.day}/{d.month}/{d.year % 100:02d}"
 
def _add_ten_years(dt: date) -> date:
    try:
        return dt.replace(year=dt.year + 10)
    except ValueError:
        if dt.month == 2 and dt.day == 29:
            return date(dt.year + 10, 2, 28)
        raise
 
today_dt = now_in_bogota().date()
primer_dia_mes = date(today_dt.year, today_dt.month, 1)
fecha_inicio = _format_d_m_yy(primer_dia_mes)
fecha_fin    = _format_d_m_yy(_add_ten_years(primer_dia_mes))
 
time.sleep(1)
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechDesde_input"]'))).clear()
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechDesde_input"]'))).send_keys(fecha_inicio)
time.sleep(1)
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechasta_input"]'))).clear()
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechasta_input"]'))).send_keys(fecha_fin)
 
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:btnDownload"]/span[2]'))).click()
 
file_acuerdo = wait_for_download_complete(TMP_DOWNLOAD, timeout=600)
move_and_upload(
    file_acuerdo,
    ACUERDOS_DIR,
    final_base="Acuerdos_Promotora",
    s3_prefix=S3_PREFIX_ACUERDOS
)
 
print("[DONE] Proceso finalizado.")
driver.quit()