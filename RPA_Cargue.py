import os
import time
from datetime import datetime
import sys
import re

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from dotenv import load_dotenv

# ===================== CONFIGURACIÓN =====================
load_dotenv()
USERNAME_VG = os.getenv("USERNAME_VG")
PASSWORD_VG = os.getenv("PASSWORD_VG")

CARPETA_PREDICTIVO = "Predictivo"
CARPETA_SMS = "Mensaje_Texto"
CARPETA_LOGS = "Logs"
LOG_PATH = os.path.join(CARPETA_LOGS, "cargues_log.csv")

# Lotes (si existen)
CARPETA_PRED_LOTES = os.path.join(CARPETA_PREDICTIVO, "lotes")
CARPETA_SMS_LOTES  = os.path.join(CARPETA_SMS, "lotes")

# Espera fija ENTRE PREDICTIVO y SMS (3 minutos)
TIEMPO_ESPERA_ENTRE_CARGUES = 180  # 3 * 60

# Si tu portal se demora mucho procesando, ajusta
TIMEOUT_CARGUE_SEGUNDOS = 240  # 4 minutos
PAUSA_ENTRE_ARCHIVOS = 2       # mini pausa “humana” entre subidas

# ===================== HELPERS =====================
def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def append_log(tipo: str, archivo: str, status: str, detalle: str):
    """Guarda el log en formato CSV (sep=';')."""
    ensure_dir(CARPETA_LOGS)
    header_needed = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", encoding="utf-8", newline="") as f:
        if header_needed:
            f.write("timestamp;tipo;archivo;status;detalle\n")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        detalle = (detalle or "").replace("\n", " ").replace(";", ",")
        f.write(f"{ts};{tipo};{archivo};{status};{detalle}\n")

def has_files_in_dir(directory: str) -> bool:
    full = os.path.join(os.getcwd(), directory)
    if not os.path.exists(full):
        return False
    return any(os.path.isfile(os.path.join(full, f)) for f in os.listdir(full))

def get_latest_file(directory: str) -> str:
    """Devuelve el archivo más reciente dentro de una carpeta."""
    full = os.path.join(os.getcwd(), directory)
    files = [os.path.join(full, f) for f in os.listdir(full) if os.path.isfile(os.path.join(full, f))]
    if not files:
        raise FileNotFoundError(f"No hay archivos en {directory}")
    return max(files, key=os.path.getmtime)

def list_files_sorted(directory: str):
    """
    Retorna lista de rutas absolutas a archivos ordenados.
    - Si el nombre contiene '_lote_###' ordena por ese número
    - Si no, ordena por fecha de modificación ascendente
    """
    full = os.path.join(os.getcwd(), directory)
    if not os.path.exists(full):
        return []

    files = [os.path.join(full, f) for f in os.listdir(full) if os.path.isfile(os.path.join(full, f))]
    if not files:
        return []

    lote_regex = re.compile(r"_lote_(\d{1,6})", re.IGNORECASE)

    def sort_key(path):
        name = os.path.basename(path)
        m = lote_regex.search(name)
        if m:
            return (0, int(m.group(1)))
        return (1, os.path.getmtime(path))

    return sorted(files, key=sort_key)

def get_files_flexible(folder_lotes: str, folder_base: str):
    """
    Busca archivos para cargar:
    1) si hay lotes en folder_lotes -> retorna todos ordenados
    2) si no, si hay archivos en folder_base -> retorna SOLO el más reciente (como antes)
    3) si no, retorna []
    """
    if has_files_in_dir(folder_lotes):
        return list_files_sorted(folder_lotes)
    if has_files_in_dir(folder_base):
        return [get_latest_file(folder_base)]
    return []

def click_if_present(driver, by, selector, timeout=3):
    try:
        WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, selector))).click()
        return True
    except Exception:
        return False

def enviar_archivo(driver, ruta_archivo: str, file_input_name="mainForm:fileUpload_input"):
    """Adjunta el archivo y presiona 'Cargar/Subir' si existe ese botón."""
    file_input = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.NAME, file_input_name)))
    file_input.send_keys(ruta_archivo)

    clicked = (
        click_if_present(driver, By.XPATH, '//*[@id="mainForm:fileUpload"]/div[1]/button[1]', timeout=5)
        or click_if_present(driver, By.CSS_SELECTOR, ".ui-fileupload-upload", timeout=3)
        or click_if_present(driver, By.XPATH, "//button[contains(.,'Subir') or contains(.,'Cargar')]", timeout=3)
    )
    return bool(clicked)

def wait_upload_finished(driver, timeout=240):
    """
    Espera a que el proceso de cargue termine.
    Señales típicas PrimeFaces:
    - overlay/progress desaparece
    - aparece mensaje de éxito/error
    """
    t0 = time.time()

    def overlay_visible():
        try:
            overlays = driver.find_elements(By.CSS_SELECTOR, ".ui-widget-overlay, .ui-blockui, .ui-blockui-content")
            return any(o.is_displayed() for o in overlays)
        except Exception:
            return False

    def has_message():
        try:
            msgs = driver.find_elements(
                By.CSS_SELECTOR,
                ".ui-growl-message, .ui-messages-info, .ui-messages-error, .ui-message-info, .ui-message-error"
            )
            return any(m.is_displayed() for m in msgs)
        except Exception:
            return False

    # margen inicial: puede aparecer overlay o mensaje
    start_deadline = time.time() + 4
    while time.time() < start_deadline:
        if overlay_visible() or has_message():
            break
        time.sleep(0.4)

    # esperar fin overlay si existe
    while overlay_visible():
        if time.time() - t0 > timeout:
            raise TimeoutException("Timeout esperando desaparición de overlay/progress")
        time.sleep(0.6)

    # intentar leer si hubo error
    try:
        if driver.find_elements(By.CSS_SELECTOR, ".ui-messages-error, .ui-message-error"):
            return ("ERROR", "Se detectó mensaje de error en UI")
        if driver.find_elements(By.CSS_SELECTOR, ".ui-messages-info, .ui-message-info, .ui-growl-message"):
            return ("OK", "Se detectó mensaje informativo/éxito en UI")
    except Exception:
        pass

    return ("OK", "Finalizado sin mensaje explícito (best-effort)")

def cargar_archivos_secuencial(driver, tipo: str, rutas: list):
    """
    Carga archivos uno por uno y espera fin por cada cargue.
    """
    if not rutas:
        return

    print(f"[INFO] {tipo}: se cargarán {len(rutas)} archivo(s).")
    for idx, ruta in enumerate(rutas, start=1):
        nombre = os.path.basename(ruta)
        print(f"[{tipo}] ({idx}/{len(rutas)}) Cargando: {nombre}")

        try:
            # a veces el input queda “bloqueado” hasta abrir el widget
            click_if_present(driver, By.XPATH, '//*[@id="mainForm:somConfigCagues"]/div[3]/span', timeout=2)

            clicked = enviar_archivo(driver, ruta)
            append_log(tipo, nombre, "ENVIADO", f"clicked_upload_button={clicked}")

            status, detalle = wait_upload_finished(driver, timeout=TIMEOUT_CARGUE_SEGUNDOS)
            append_log(tipo, nombre, status, detalle)

            # borrar archivo al finalizar (igual que tu lógica)
            try:
                os.remove(ruta)
            except Exception as e:
                append_log(tipo, nombre, "WARN", f"No se pudo borrar: {e}")

            time.sleep(PAUSA_ENTRE_ARCHIVOS)

        except Exception as e:
            append_log(tipo, nombre, "ERROR", f"Falló cargue: {e}")
            print(f"[WARN] {tipo}: error cargando {nombre}: {e}")
            # seguimos con el siguiente archivo

# ===================== DRIVER =====================
options = Options()
options.add_experimental_option("detach", True)
driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, 20)

try:
    # ---------------- LOGIN ----------------
    driver.get('https://visiong.iagree.co/iAgree/faces/login.xhtml')
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

    select_promotora_octubre = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:dtCampanas:0:j_idt204"]')))
    time.sleep(1)
    select_promotora_octubre.click()

    # ---------------- IR A IMPORTAR ----------------
    sidebar_import = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:mnImportar"]/a')))
    time.sleep(1)
    sidebar_import.click()

    # ---------------- TIPO DE CARGUE (MISMO FLUJO QUE TENÍAS) ----------------
    seleccione_tipo = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:j_idt149_label"]')))
    time.sleep(1)
    seleccione_tipo.click()

    gestion_masiva_arbol_producto = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:j_idt149_10"]')))
    gestion_masiva_arbol_producto.click()

    time.sleep(1)
    seleccion_estructura = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:somConfigCagues"]/div[3]')))
    seleccion_estructura.click()

    # 👇 Dejas el mismo XPATH que ya tenías (no lo cambiamos)
    sms = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="mainForm:somConfigCagues_2"]')))
    sms.click()

    # ===================== 1) CARGAR PREDICTIVO (POR LOTES) =====================
    rutas_pred = get_files_flexible(CARPETA_PRED_LOTES, CARPETA_PREDICTIVO)
    tiene_pred = bool(rutas_pred)

    if tiene_pred:
        print("[INFO] Se encontraron archivos Predictivo para cargar.")
        cargar_archivos_secuencial(driver, "PREDICTIVO", rutas_pred)
        append_log("PREDICTIVO", "-", "INFO", f"Total archivos cargados: {len(rutas_pred)}")
    else:
        print("[INFO] No hay archivos Predictivos para cargar.")

    # ===================== ESPERA ENTRE PREDICTIVO y SMS =====================
    if tiene_pred:
        print(f"[INFO] Esperando {TIEMPO_ESPERA_ENTRE_CARGUES/60:.0f} minutos antes de iniciar el cargue de SMS...")
        time.sleep(TIEMPO_ESPERA_ENTRE_CARGUES)

    # ===================== 2) CARGAR SMS (POR LOTES) =====================
    rutas_sms = get_files_flexible(CARPETA_SMS_LOTES, CARPETA_SMS)
    tiene_sms = bool(rutas_sms)

    if tiene_sms:
        print("[INFO] Se encontraron archivos SMS para cargar.")
        cargar_archivos_secuencial(driver, "SMS", rutas_sms)
        append_log("SMS", "-", "INFO", f"Total archivos cargados: {len(rutas_sms)}")
    else:
        print("[INFO] No hay archivos SMS para cargar.")

    if not tiene_sms and not tiene_pred:
        print("⚠️ No se encontraron archivos para cargar en ninguna carpeta.")
    else:
        print("✅ Proceso completado.")

except Exception as e:
    append_log("RPA", "-", "ERROR", f"Excepción no controlada: {e}")
    print("ERROR:", e)
    sys.exit(1)
finally:
    driver.quit()