import os
import time
import glob
import shutil
from datetime import datetime, date

import pyotp  # pip install pyotp

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
# Utilidades
# =========================
def wait_for_download_complete(download_dir: str, timeout: int = 600) -> str:
    end = time.time() + timeout
    last_path, last_size, stable = None, -1, 0
    while time.time() < end:
        if glob.glob(os.path.join(download_dir, "*.crdownload")):
            time.sleep(1); continue
        files = [f for f in glob.glob(os.path.join(download_dir, "*")) if os.path.isfile(f)]
        if not files:
            time.sleep(1); continue
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

def run_date_str():
    return now_in_bogota().strftime("%Y-%m-%d")

def get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
    )

def move_and_upload(local_src, target_dir, final_base, s3_prefix):
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

def safe_click(locator, desc="", max_retries=3):
    for attempt in range(1, max_retries + 1):
        try:
            el = wait.until(EC.element_to_be_clickable(locator))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.5)
            el.click()
            if desc:
                print(f"[CLICK] {desc} (intento {attempt}) OK.")
            return
        except ElementClickInterceptedException:
            try:
                el = driver.find_element(*locator)
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
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
    Ingresa el codigo TOTP en el modal de Iagree con reintento automatico.

    Criterio de exito: el input del modal DESAPARECE de la pantalla (modal cerrado).
    Criterio de fallo: el input sigue visible 5s despues de hacer clic en Verificar.

    Esto evita falsos positivos por banners de error que quedan en el DOM
    de intentos anteriores.
    """
    input_xpath = '//input[contains(@placeholder,"000000") or contains(@placeholder,"0 0 0 0 0 0")]' 
    boton_texto = "Verificar y entrar" if contexto == "login" else "Verificar y descargar"
    boton_xpath = f'//button[contains(., "{boton_texto}")]' 
    totp        = pyotp.TOTP(MFA_SECRET)
    wait_corto  = WebDriverWait(driver, 5)  # timeout corto solo para detectar cierre del modal

    for intento in range(1, max_reintentos + 1):

        # Espera a que el modal este visible antes de cada intento
        wait.until(EC.visibility_of_element_located((By.XPATH, input_xpath)))

        # Si quedan < 3s para que el codigo expire, espera el siguiente ciclo
        segundos_restantes = 30 - (int(time.time()) % 30)
        if segundos_restantes < 3:
            print(f"[MFA] Codigo por expirar en {segundos_restantes}s, esperando el siguiente...")
            time.sleep(segundos_restantes + 1)

        codigo = totp.now()
        segundos_restantes = 30 - (int(time.time()) % 30)
        print(f"[MFA] Intento {intento}/{max_reintentos} | contexto={contexto} | "
              f"codigo={codigo} | expira en {segundos_restantes}s")

        # Escribe el codigo y hace clic en Verificar
        campo = wait.until(EC.element_to_be_clickable((By.XPATH, input_xpath)))
        campo.clear()
        campo.send_keys(codigo)
        time.sleep(0.5)
        wait.until(EC.element_to_be_clickable((By.XPATH, boton_xpath))).click()

        # Criterio de exito: el input del modal desaparece (Iagree cerro el modal)
        # Si el codigo es rechazado, el modal permanece abierto y esto lanza TimeoutException
        try:
            wait_corto.until(EC.invisibility_of_element_located((By.XPATH, input_xpath)))
            print(f"[MFA] Codigo {contexto} verificado correctamente (intento {intento}).")
            return
        except TimeoutException:
            print(f"[MFA] Codigo rechazado (modal sigue visible) en intento {intento}. "
                  "Esperando proximo ciclo de 30s para reintentar...")
            tiempo_espera = 30 - (int(time.time()) % 30) + 1
            time.sleep(tiempo_espera)

    raise RuntimeError(
        f"[MFA] Fallo la verificacion MFA tras {max_reintentos} intentos ({contexto}). "
        "Revisa el MFA_SECRET en el .env o el estado de Iagree."
    )

# =========================
# Flujo principal
# =========================
driver.get('https://visiong.iagree.co/iAgree/faces/login.xhtml')
driver.maximize_window()

# --- Login ---
# XPaths por placeholder: robustos ante cambios de IDs dinámicos de JSF
XP_USUARIO    = '//input[@placeholder="Usuario" or contains(@placeholder,"suario")]'
XP_PASSWORD   = '//input[@placeholder="Contraseña" or @type="password"]'
XP_CAPTCHA_IN = '//input[contains(@placeholder,"aptcha") or contains(@placeholder,"APTCHA")]'

wait.until(EC.presence_of_element_located((By.XPATH, XP_USUARIO)))
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

# ============ 1) Gestión Universo ============
select_primefaces_option_by_text(driver, "Seleccione Uno", "Gestión Universo")

def _format_d_m_yy(d: date) -> str:
    return f"{d.day}/{d.month}/{d.year % 100:02d}"

today_dt             = now_in_bogota().date()
fecha_inicio_gestion = _format_d_m_yy(today_dt)
fecha_fin_gestion    = _format_d_m_yy(today_dt)

time.sleep(1)
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechDesde_input"]'))).send_keys(fecha_inicio_gestion)
time.sleep(1)
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechasta_input"]'))).send_keys(fecha_fin_gestion)
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:btnDownload"]/span[2]'))).click()

# --- MFA Descarga Gestiones ---
ingresar_mfa(contexto="descarga")

file_gestion = wait_for_download_complete(TMP_DOWNLOAD, timeout=600)
move_and_upload(file_gestion, GESTIONES_DIR, "Gestiones_Promotora", S3_PREFIX_GESTIONES)

# ============ 2) Matriz de Acuerdos ============
time.sleep(2)
select_primefaces_option_by_text(driver, "Seleccione Uno", "Informe Matriz Acuerdos")

def _add_ten_years(dt: date) -> date:
    try:
        return dt.replace(year=dt.year + 10)
    except ValueError:
        if dt.month == 2 and dt.day == 29:
            return date(dt.year + 10, 2, 28)
        raise

today_dt       = now_in_bogota().date()
primer_dia_mes = date(today_dt.year, today_dt.month, 1)
fecha_inicio   = _format_d_m_yy(primer_dia_mes)
fecha_fin      = _format_d_m_yy(_add_ten_years(primer_dia_mes))

time.sleep(1)
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechDesde_input"]'))).clear()
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechDesde_input"]'))).send_keys(fecha_inicio)
time.sleep(1)
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechasta_input"]'))).clear()
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:fechasta_input"]'))).send_keys(fecha_fin)
wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:pgMenuExportacion:btnDownload"]/span[2]'))).click()

# --- MFA Descarga Acuerdos ---
ingresar_mfa(contexto="descarga")

file_acuerdo = wait_for_download_complete(TMP_DOWNLOAD, timeout=600)
move_and_upload(file_acuerdo, ACUERDOS_DIR, "Acuerdos_Promotora", S3_PREFIX_ACUERDOS)

print("[DONE] Ambos archivos descargados, clasificados y subidos a S3.")
driver.quit()