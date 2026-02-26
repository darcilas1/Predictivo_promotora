import os
import time
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from dotenv import load_dotenv
 
# ===================== CONFIGURACIÓN =====================
load_dotenv()
 
USERNAME_VG = os.getenv("USERNAME_VG")
PASSWORD_VG = os.getenv("PASSWORD_VG")
 
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
 
    wait.until(EC.presence_of_element_located((By.NAME, "loginForm:j_idt22")))
    driver.find_element(By.NAME, "loginForm:j_idt22").send_keys(USERNAME_VG)
    driver.find_element(By.NAME, "loginForm:j_idt24").send_keys(PASSWORD_VG)
    time.sleep(2)
 
    captcha_text = driver.find_element(By.ID, "captcha")
    captcha_input = driver.find_element(By.NAME, "loginForm:j_idt26")
    captcha_input.send_keys(captcha_text.text)
    captcha_input.send_keys(Keys.RETURN)
 
    # ---------------- SELECCIÓN CAMPAÑA ----------------
    wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:dtGrupoCampanas_data"]/tr[20]')))
    time.sleep(1)
    driver.find_element(By.XPATH, '//*[@id="mainForm:dtGrupoCampanas_data"]/tr[20]').click()
 
    select_promotora_octubre = wait.until(
        EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:dtCampanas:0:j_idt204"]'))
    )
    time.sleep(1)
    select_promotora_octubre.click()
 
    # ---------------- IR A MULTICANAL ----------------
    sidebar_multicanal = wait.until(
        EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:mnMulticanal"]/a'))
    )
    time.sleep(2)
    sidebar_multicanal.click()
 
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