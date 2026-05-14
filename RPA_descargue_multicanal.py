import os
import time
import pyotp
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from dotenv import load_dotenv
from crm_navigation import click_by_visible_text, click_campaign_detail_arrow, click_campaign_group_by_text
 
# ===================== CONFIGURACIÓN =====================
load_dotenv()
 
USERNAME_VG = os.getenv("USERNAME_VG")
PASSWORD_VG = os.getenv("PASSWORD_VG")
MFA_SECRET  = os.getenv("MFA_SECRET")
 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CARPETA_MULTICANAL = os.path.join(BASE_DIR, "Multicanal")
 
# ===================== HELPERS =====================
def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)
 
def list_files(folder: str):
    return {
        f for f in os.listdir(folder)
        if os.path.isfile(os.path.join(folder, f))
    }
 
def wait_for_new_download(folder: str, before_files: set, timeout: int = 180):
    end_time = time.time() + timeout
 
    new_name = None
    while time.time() < end_time:
        now = list_files(folder)
        diff = now - before_files
        if diff:
            candidates = list(diff)
            candidates.sort(
                key=lambda x: os.path.getmtime(os.path.join(folder, x)),
                reverse=True
            )
            new_name = candidates[0]
            break
        time.sleep(0.5)
 
    if not new_name:
        raise TimeoutError("No apareció ningún archivo nuevo en la carpeta de descargas.")
 
    def current_state():
        return list_files(folder)
 
    last_final = None
    stable_count = 0
    last_size = None
 
    while time.time() < end_time:
        files_now = current_state()
 
        downloading = [f for f in files_now if f.endswith(".crdownload")]
        if downloading:
            time.sleep(0.5)
            continue
 
        diff_final = [f for f in (files_now - before_files) if not f.endswith(".crdownload")]
        if not diff_final:
            time.sleep(0.5)
            continue
 
        diff_final.sort(
            key=lambda x: os.path.getmtime(os.path.join(folder, x)),
            reverse=True
        )
        last_final = diff_final[0]
        final_path = os.path.join(folder, last_final)
 
        size = os.path.getsize(final_path)
        if last_size is None or size != last_size:
            stable_count = 0
            last_size = size
            time.sleep(0.7)
            continue
 
        stable_count += 1
        if stable_count >= 2:
            return final_path
 
        time.sleep(0.7)
 
    raise TimeoutError("La descarga no finalizó o el archivo no se estabilizó a tiempo.")
 
def click_with_retry(driver, wait, locator, attempts: int = 3):
    """
    Hace click en un elemento de forma robusta:
    - Lo localiza de nuevo en cada intento
    - Espera a que sea clickable
    - Reintenta si el elemento se vuelve 'stale'
    """
    for i in range(attempts):
        try:
            elem = wait.until(EC.element_to_be_clickable(locator))
            elem.click()
            return
        except StaleElementReferenceException:
            print(f"[WARN] Elemento stale en intento {i+1}, reintentando...")
            time.sleep(1)
        except TimeoutException:
            print("[ERROR] No se encontró el botón dentro del tiempo de espera.")
            raise
    raise StaleElementReferenceException("No se pudo hacer click en el elemento después de varios intentos.")
 
def ingresar_mfa(driver, wait, contexto: str = "login", max_reintentos: int = 3):
    """
    Ingresa el codigo TOTP en el modal de Iagree con reintento automatico.
    """
    input_xpath = '//input[contains(@placeholder,"000000") or contains(@placeholder,"0 0 0 0 0 0")]'
    boton_texto = "Verificar y entrar" if contexto == "login" else "Verificar y descargar"
    boton_xpath = f'//button[contains(., "{boton_texto}")]'
    totp = pyotp.TOTP(MFA_SECRET)
    wait_corto = WebDriverWait(driver, 5)

    for intento in range(1, max_reintentos + 1):
        wait.until(EC.visibility_of_element_located((By.XPATH, input_xpath)))

        segundos_restantes = 30 - (int(time.time()) % 30)
        if segundos_restantes < 3:
            print(f"[MFA] Codigo por expirar en {segundos_restantes}s, esperando el siguiente...")
            time.sleep(segundos_restantes + 1)

        codigo = totp.now()
        segundos_restantes = 30 - (int(time.time()) % 30)
        print(
            f"[MFA] Intento {intento}/{max_reintentos} | contexto={contexto} | "
            f"codigo={codigo} | expira en {segundos_restantes}s"
        )

        campo = wait.until(EC.element_to_be_clickable((By.XPATH, input_xpath)))
        campo.clear()
        campo.send_keys(codigo)
        time.sleep(0.5)
        wait.until(EC.element_to_be_clickable((By.XPATH, boton_xpath))).click()

        try:
            wait_corto.until(EC.invisibility_of_element_located((By.XPATH, input_xpath)))
            print(f"[MFA] Codigo {contexto} verificado correctamente (intento {intento}).")
            return
        except TimeoutException:
            print(
                f"[MFA] Codigo rechazado (modal sigue visible) en intento {intento}. "
                "Esperando proximo ciclo de 30s para reintentar..."
            )
            tiempo_espera = 30 - (int(time.time()) % 30) + 1
            time.sleep(tiempo_espera)

    raise RuntimeError(
        f"[MFA] Fallo la verificacion MFA tras {max_reintentos} intentos ({contexto}). "
        "Revisa el MFA_SECRET en el .env o el estado de Iagree."
    )

# ===================== INICIO =====================
ensure_dir(CARPETA_MULTICANAL)
 
prefs = {
    "download.default_directory": CARPETA_MULTICANAL,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True
}
 
options = Options()
options.add_experimental_option("prefs", prefs)
options.add_experimental_option("detach", True)
 
driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, 20)
 
try:
    # ---------------- LOGIN ----------------
    driver.get("https://visiong.iagree.co/iAgree/faces/login.xhtml")
    driver.maximize_window()
 
    XP_USUARIO = '//input[@placeholder="Usuario" or contains(@placeholder,"suario")]'
    XP_PASSWORD = '//input[@placeholder="ContraseÃ±a" or @type="password"]'
    XP_CAPTCHA_IN = '//input[contains(@placeholder,"aptcha") or contains(@placeholder,"APTCHA")]'

    wait.until(EC.presence_of_element_located((By.XPATH, XP_USUARIO)))
    time.sleep(1)
    driver.find_element(By.XPATH, XP_USUARIO).send_keys(USERNAME_VG)
    time.sleep(1)
    driver.find_element(By.XPATH, XP_PASSWORD).send_keys(PASSWORD_VG)
    time.sleep(2)
 
    captcha_text = driver.find_element(By.ID, "captcha")
    captcha_input = driver.find_element(By.XPATH, XP_CAPTCHA_IN)
    time.sleep(1)
    captcha_input.send_keys(captcha_text.text.strip())
    time.sleep(1)
    captcha_input.send_keys(Keys.RETURN)

    time.sleep(1)
    ingresar_mfa(driver, wait, contexto="login")
 
    # ---------------- SELECCIÓN CAMPAÑA ----------------
    time.sleep(1)
    click_campaign_group_by_text(driver)
    time.sleep(1)
    click_campaign_detail_arrow(driver)
 
    # ---------------- IR A MULTICANAL ----------------
    time.sleep(2)
    click_by_visible_text(driver, "Multicanal", desc="Menú Multicanal")
 
    # 🔥 Snapshot ANTES de descargar
    before = list_files(CARPETA_MULTICANAL)
 
    # ---------------- DESCARGAR MULTICANAL ----------------
    descargar_locator = (By.XPATH, '//*[@id="mainForm:DownloadButtonAcuerdoCastigo"]')
 
    # IMPORTANTE: ya no usamos time.sleep(5) con el elemento guardado
    click_with_retry(driver, wait, descargar_locator, attempts=4)
 
    # ---------------- ESPERAR DESCARGA ----------------
    downloaded_path = wait_for_new_download(CARPETA_MULTICANAL, before_files=before, timeout=240)
 
    print(f"✅ Descarga completada y estable: {downloaded_path}")
 
finally:
    driver.quit()
    print("Proceso finalizado.")
