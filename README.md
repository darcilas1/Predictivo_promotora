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

| Día | Hora |
|---|---|
| Lunes a Viernes | 7:05 PM |
| Sábados | 3:05 PM |

---

## 🗂 Estructura del proyecto

```
Predictivo_promotora/
│
├── orquestador.py                    # Orquestador principal
├── run_orquestador.bat               # Script de arranque (activa venv y lanza el orquestador)
│
├── RPA_descargue_multicanal.py       # Paso 1: Descarga el archivo Multicanal desde el CRM
├── main_predictivo.py                # Paso 2: Procesa y genera el CSV de cargue predictivo
├── RPA_Cargue.py                     # Paso 3: Carga el CSV predictivo al CRM
├── descargue_gestiones_acuerdos.py   # Paso 4: Descarga Gestiones y Acuerdos → S3
├── contingencia_descargue_ges_ac.py  # Paso 5: Contingencia de descarga de Gestiones y Acuerdos
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

# API Wolkvox
OP04_SERVER=<server_wolkvox>
OP04_TOKEN=<token_wolkvox>

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

### Forma recomendada (producción)

Ejecutar el archivo **`run_orquestador.bat`** con doble clic o desde el Programador de tareas de Windows:

```bat
run_orquestador.bat
```

Este script:
1. Se posiciona en la carpeta del proyecto.
2. Activa el entorno virtual (`venv`).
3. Lanza `orquestador.py`.

### Forma manual (desarrollo / debug)

```bash
# Con el venv activo
python orquestador.py
```

---

## 🔄 Flujo detallado del orquestador

```
[INICIO]
    │
    ▼
[1] RPA_descargue_multicanal.py   → Descarga el archivo Multicanal del CRM (Selenium)
    │  (falla → aborta todo + notifica Teams)
    ▼
[2] main_predictivo.py            → Consulta API Wolkvox campaign_3, filtra PROMOTORA,
    │                               genera CSV de cargue en /Predictivo/
    │  (falla → aborta todo + notifica Teams)
    ▼
[3] RPA_Cargue.py                 → Carga el CSV predictivo al CRM (Selenium, por lotes si aplica)
    │  (falla → aborta todo + notifica Teams)
    │
    ▼
[ESPERA 5 MINUTOS]
    │
    ▼
[4] descargue_gestiones_acuerdos.py → Descarga Gestión Universo y Matriz de Acuerdos,
    │                                  los sube a S3 (datos-vg/PROMOTORA/)
    │  (falla → notifica Teams, pero la contingencia IGUAL se ejecuta)
    │
    ▼
[ESPERA 40 MINUTOS]
    │
    ▼
[5] contingencia_descargue_ges_ac.py → Re-descarga y sube a S3 si la validación
                                        de Gestión Universo corresponde al día actual
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
