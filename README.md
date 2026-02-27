# RPA – Predictivo Promotora

Automatización para preparar y cargar las gestiones del predictivo de la campaña **Promotora**, y descargar los reportes de gestiones y acuerdos del CRM para cargarlos a S3.

---

## 📋 Descripción general

Este proyecto ejecuta de forma orquestada y secuencial los siguientes pasos:

1. **Descarga del Multicanal** desde el CRM vía Selenium.
2. **Procesamiento del Predictivo**: consulta la API Wolkvox (`campaign_3`) filtrando los registros de Promotora del día, genera el archivo CSV de cargue.
3. **Cargue del Predictivo** al CRM vía Selenium.
4. *(Espera 5 minutos)*
5. **Descarga de Gestiones y Acuerdos** del CRM y subida a S3.
6. *(Espera 40 minutos)*
7. **Contingencia**: vuelve a descargar Gestiones y Acuerdos (si aplica según validación) y los sube a S3.

Al finalizar cada etapa, el orquestador envía notificaciones a **Microsoft Teams** (errores inmediatos + resumen final).

---

## 🕒 Horario de ejecución

| Día | Hora | Proceso |
|---|---|---|
| Lunes a Viernes | 7:05 PM | `run_orquestador.bat` (proceso principal) |
| Sábados | 3:05 PM | `run_orquestador_sabado.bat` (proceso sábado) |

---

## 🗂 Estructura del proyecto

```
Predictivo_promotora/
│
├── orquestador.py                    # Orquestador L-V
├── run_orquestador.bat               # Launcher L-V
│
├── orquetador_sabado.py              # Orquestador sábado
├── run_orquestador_sabado.bat        # Launcher sábado
│
├── RPA_descargue_multicanal.py       # Paso 1 (L-V): Descarga el archivo Multicanal desde el CRM
├── main_predictivo.py                # Paso 2 (L-V): Procesa y genera el CSV de cargue predictivo via API Wolkvox
├── RPA_Cargue.py                     # Paso 3 (L-V y Sáb.): Carga el CSV predictivo al CRM
├── descargue_gestiones_acuerdos.py   # Paso 4 (L-V): Descarga Gestiones y Acuerdos → S3
├── contingencia_descargue_ges_ac.py  # Paso 5 (L-V): Contingencia de descarga de Gestiones y Acuerdos
│
├── descarga_predictivo_sabado.py     # Paso 1 (Sáb.): Descarga datos de Databricks
├── predictivo_sabado.py             # Paso 2 (Sáb.): Prepara CSV de cargue desde datos Databricks
│
├── formatoArbolProducto.csv          # Template de columnas para el archivo de cargue
├── requirements.txt                  # Dependencias Python
├── .env                              # Variables de entorno (no subir a Git)
├── .gitignore
│
├── Multicanal/                       # Archivos descargados por RPA_descargue_multicanal.py
├── Predictivo/                       # Archivos CSV generados por main_predictivo.py
├── downloads/
│   ├── tmp/                          # Descarga temporal del driver
│   ├── Gestiones/                    # Gestiones clasificadas (archivo final)
│   └── Acuerdos/                     # Acuerdos clasificados (archivo final)
├── Logs/                             # Log de cargues (cargues_log.csv)
└── logs_orquestador/                 # Logs diarios del orquestador
```

---

## ⚙️ Requisitos previos

- **Python 3.10+**
- **Google Chrome** instalado (compatible con la versión de `chromedriver` en uso)
- **ChromeDriver** disponible en el PATH del sistema
- Entorno virtual de Python (`venv`)

---

## 🔧 Instalación

```bash
# 1. Clonar o descargar el repositorio
git clone <url-del-repositorio>
cd Predictivo_promotora

# 2. Crear y activar el entorno virtual
python -m venv venv
venv\Scripts\activate      # Windows

# 3. Instalar dependencias
pip install -r requirements.txt
```

---

## 🔑 Variables de entorno (`.env`)

Crear el archivo `.env` en la raíz del proyecto con las siguientes variables:

```env
# Credenciales del CRM iAgree
USERNAME_VG=<usuario_crm>
PASSWORD_VG=<contraseña_crm>

# API Wolkvox (proceso L-V)
OP04_SERVER=<server_wolkvox>
OP04_TOKEN=<token_wolkvox>

# Databricks (proceso sábado)
SERVER_HOSTNAME=<databricks_server_hostname>
HTTP_PATH=<databricks_http_path>
ACCESS_TOKEN=<databricks_personal_access_token>

# AWS S3
AWS_ACCESS_KEY_ID=<access_key>
AWS_SECRET_ACCESS_KEY=<secret_key>
AWS_REGION=us-east-1
S3_BUCKET=<nombre_bucket>

# Microsoft Teams (webhook para notificaciones)
TEAMS_WEBHOOK_URL=https://<tu-empresa>.webhook.office.com/webhookb2/...
```

> **Nota:** El archivo `.env` está en `.gitignore` y nunca debe subirse al repositorio.

---

## 🚀 Ejecución

### Proceso L-V (principal)

Ejecutar **`run_orquestador.bat`**:

```bat
run_orquestador.bat
```

### Proceso Sábado

Ejecutar **`run_orquestador_sabado.bat`**:

```bat
run_orquestador_sabado.bat
```

### Forma manual (desarrollo / debug)

```bash
# Con el venv activo
python orquestador.py          # proceso L-V
python orquetador_sabado.py    # proceso sábado
```

---

## 🔄 Flujo detallado – Proceso L-V

```
[INICIO]
    │
    ▼
[1] RPA_descargue_multicanal.py   → Descarga Multicanal CRM (Selenium) — continúa aunque falle
    │
    ▼
[2] main_predictivo.py            → Consulta API Wolkvox campaign_3, filtra PROMOTORA,
    │                               genera CSV de cargue en /Predictivo/
    │  (falla → aborta todo)
    ▼
[3] RPA_Cargue.py                 → Carga el CSV predictivo al CRM (Selenium)
    │  (falla → aborta todo)
    │
    ▼
[ESPERA 5 MINUTOS]
    │
    ▼
[4] descargue_gestiones_acuerdos.py → Descarga Gestión Universo y Matriz de Acuerdos → S3
    │
    ▼
[ESPERA 40 MINUTOS]
    │
    ▼
[5] contingencia_descargue_ges_ac.py → Re-descarga si validación corresponde al día
    │
    ▼
[RESUMEN FINAL → Teams]
```

## 🔄 Flujo detallado – Proceso Sábado

> El token de Wolkvox no funciona los sábados a la hora de ejecución, por lo que
> los datos se obtienen directamente desde **Databricks**.

```
[INICIO]
    │
    ▼
[1] descarga_predictivo_sabado.py  → Consulta Databricks, filtra PROMOTORA del día,
    │                                 guarda CSV en /Predictivo/
    │  (falla → aborta todo)
    ▼
[2] predictivo_sabado.py           → Lee el CSV de Databricks, genera CSV de cargue
    │                                 en formato CRM en /Predictivo/
    │  (falla → aborta todo)
    ▼
[3] RPA_Cargue.py                  → Carga el CSV predictivo al CRM (Selenium)
    │
    ▼
[RESUMEN FINAL → Teams]
```

---

## 📨 Notificaciones Teams

El orquestador envía mensajes al canal de Teams configurado en `TEAMS_WEBHOOK_URL`:

| Evento | Notificación |
|---|---|
| Proceso principal falla | Mensaje inmediato con nombre del proceso |
| `descargue_gestiones_acuerdos.py` falla | Mensaje inmediato |
| `contingencia_descargue_ges_ac.py` falla | Mensaje inmediato |
| Fin de toda la ejecución | Resumen con ✅ exitosos, ❌ fallidos, ⏭ no ejecutados |

---

## 📁 Logs

| Ruta | Contenido |
|---|---|
| `logs_orquestador/orquestador_YYYYMMDD.log` | Log completo del orquestador (timestamps, stdout/stderr de cada proceso) |
| `Logs/cargues_log.csv` | Log por archivo de cada cargue realizado en `RPA_Cargue.py` |

---

## 📦 Dependencias principales (`requirements.txt`)

```
selenium
requests
python-dotenv
pandas
boto3
```

---

## 🛡 Consideraciones de seguridad

- Las credenciales del CRM, AWS y Teams se gestionan exclusivamente mediante variables de entorno en `.env`.
- El `.env` está excluido del control de versiones (`git`).
- Los archivos procesados se eliminan localmente tras una subida exitosa a S3.
