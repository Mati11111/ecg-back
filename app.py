from fastapi.middleware.cors import CORSMiddleware
import threading
import time
from datetime import datetime
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
import sqlite3
import asyncio
import queue
import math

from fastapi import FastAPI, WebSocket, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi import Body
import uvicorn

import serial
from serial.tools import list_ports
import json
import requests
import os
import csv
# ---------------------- Config ----------------------

MAX_DATOS     = 300       # Últimas muestras en memoria para /ecg
BUFFER_DB     = 50        # Lote mínimo para volcar a SQLite (ECG y BPM juntos)
BAUDRATE      = 115200    # Debe coincidir con Serial.begin(...) del Arduino
SER_TIMEOUT   = 1.0       # Timeout de lectura en segundos
RETRY_SECS    = 1.0       # Reintento de conexión cada 1s

#FS            = 853       # Frecuencia de muestreo estimada (informativa)
FS       = 125

# Detector de BPM sencillo (umbral + refractario)
UMBRAL       = 400
REFRACT_SEC  = 0.300
RR_MIN       = 0.300
RR_MAX       = 2.000

# Señal de prueba (senoide)
#_test_cfg = {
#    "enabled": False,   # Si True, reemplaza val por senoide
#    "freq": 1.0,        # Hz
#    "amp": 800,         # amplitud en cuentas (mantener << 0x7FFFFF)
#    "offset": 0,        # offset DC en cuentas
#}
#_test_state = {
#    "phase": 0.0,
#    "last_t": None,     # perf_counter del último sample
#}

# Senal ed prueba 2
_test_cfg_2 = {
    "enabled":"False",
    "freq": 1.0,    # Frecuencia de la señal en Hz
    "amp": 1.0,     # Amplitud máxima = 1
    "offset": 0.0,  # Offset 0 para -1 a 1
}
_test_state_2 = {
    "last_t": None,
    "phase": 0.0
}

# ---------------------- Estado ----------------------

datos_ecg = deque(maxlen=MAX_DATOS)  # [{"timestamp": str, "value": int}, ...]
db_lock   = threading.Lock()
activar_escritura = False

buffer_db_ecg = []  # [(ts, val), ...]
buffer_db_bpm = []  # [(ts, bpm), ...]

_last_bpm = None
_last_bpm_ts = None

_last_val_for_peak = 0
_last_peak_time = 0.0

# WS: clientes y cola thread-safe
ws_clients = set()
ws_queue = queue.Queue(maxsize=4096)  # valores int (crudos)

HDR = b'\xAA\x55'

# Carpeta y DB
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)




# ---------------------- DB ----------------------

def conectar_sqlite(nombre_bd="ecg_data.db"):
    ruta_bd = DATA_DIR / nombre_bd
    conn = sqlite3.connect(ruta_bd, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.execute("PRAGMA temp_store=MEMORY;")
    cur.execute("PRAGMA cache_size=-2000;")  # ~2MB
    cur.execute('''
        CREATE TABLE IF NOT EXISTS ecg_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            value INTEGER NOT NULL
        );
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS bpm_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            bpm INTEGER NOT NULL
        );
    ''')
    conn.commit()
    return conn

db_conn = conectar_sqlite()

def flush_buffers_if_needed(cursor, force=False):
    """
    Inserta ECG y BPM en UNA MISMA transacción cuando cualquiera
    de los dos buffers alcanza el tamaño de lote o si 'force' es True.
    Importante: si ocurre un error, NO se limpian los buffers;
    se reintenta en el siguiente ciclo.
    """
    global buffer_db_ecg, buffer_db_bpm

    ecg_ready = len(buffer_db_ecg) >= BUFFER_DB
    bpm_ready = len(buffer_db_bpm) >= BUFFER_DB

    if not (force or ecg_ready or bpm_ready):
        return False

    try:
        with db_lock:
            cursor.execute("BEGIN IMMEDIATE;")
            if buffer_db_ecg:
                cursor.executemany(
                    "INSERT INTO ecg_data (timestamp, value) VALUES (?, ?)",
                    buffer_db_ecg
                )
            if buffer_db_bpm:
                cursor.executemany(
                    "INSERT INTO bpm_data (timestamp, bpm) VALUES (?, ?)",
                    buffer_db_bpm
                )
            db_conn.commit()
            # Sólo si COMMIT fue exitoso, limpiamos los buffers
            buffer_db_ecg.clear()
            buffer_db_bpm.clear()
        return True
    except Exception as e:
        # Rollback y mantenemos los buffers tal cual para reintentar luego
        try:
            db_conn.rollback()
        except:
            pass
        print(f"Error al volcar lotes a DB: {e}. Se reintentará en el siguiente ciclo.")
        return False

# === Cambio dinámico de BD ===
CURRENT_DB_NAME = "ecg_data.db"  # nombre actual (se ajusta al iniciar si ya abriste otra)
DB_SWITCH_COUNTER = 0            # para avisar a hilos que renueven cursor

def _sanitize_basename(name: str) -> str:
    import re
    base = (name or "").strip()
    if base.lower().endswith(".db"):
        base = base[:-3]
    base = re.sub(r"[^A-Za-z0-9_\-]+", "_", base).strip("_-") or "ecg_data"
    return base

def _unique_db_filename(base: str) -> str:
    base = _sanitize_basename(base)
    fname = f"{base}.db"
    p = DATA_DIR / fname
    i = 1
    while p.exists():
        fname = f"{base}_{i}.db"
        p = DATA_DIR / fname
        i += 1
    return fname

def _current_db_path_from_conn() -> Path:
    try:
        cur = db_conn.cursor()
        cur.execute("PRAGMA database_list;")
        row = cur.fetchone()
        if row and len(row) >= 3 and row[2]:
            return Path(row[2])
    except Exception:
        pass
    return DATA_DIR / CURRENT_DB_NAME

# ---------------------- BPM sencillo ----------------------

def detectar_bpm_sencillo(valor_actual: int, ts_str: str):
    """
    Pico = cruce ascendente del umbral + refractario.
    BPM = 60 / RR del último intervalo válido.
    Devuelve BPM nuevo (int) si se calcula; si no, None.
    """
    global _last_val_for_peak, _last_peak_time, _last_bpm, _last_bpm_ts

    v = valor_actual
    bpm_out = None

    if v > UMBRAL and _last_val_for_peak <= UMBRAL:
        t_now = time.time()
        if _last_peak_time == 0.0:
            _last_peak_time = t_now
        else:
            rr = t_now - _last_peak_time
            if rr >= REFRACT_SEC and RR_MIN <= rr <= RR_MAX:
                bpm = round(60.0 / rr)
                _last_bpm = bpm
                _last_bpm_ts = ts_str
                bpm_out = bpm
                _last_peak_time = t_now
            elif rr >= REFRACT_SEC:
                _last_peak_time = t_now

    _last_val_for_peak = v
    return bpm_out

# ---------------------- Señal de prueba ----------------------


def gen_test_sample_normalized_2():
    now = time.perf_counter()
    dt = 1.0 / FS

    last_t = _test_state_2["last_t"]
    if last_t is None:
        target_t = now
    else:
        target_t = last_t + dt
        if now < target_t:
            time.sleep(target_t - now)

    _test_state_2["last_t"] = target_t

    # Avanza fase y genera senoide normalizada
    phase = _test_state_2["phase"]
    phase += 2.0 * math.pi * _test_cfg_2["freq"] / FS
    if phase > 2.0 * math.pi:
        phase -= 2.0 * math.pi
    _test_state_2["phase"] = phase

    val = _test_cfg_2["offset"] + _test_cfg_2["amp"] * math.sin(phase)

    return val


def _gen_test_sample():
    """
    Genera y retorna un valor entero de senoide a FS.
    Controla el tiempo para emitir exactamente ~FS muestras/seg.
    """
    # Programación por tiempo para mantener la tasa FS
    now = time.perf_counter()
    dt = 1.0 / max(1, FS)

    last_t = _test_state["last_t"]
    if last_t is None:
        # Primera muestra
        target_t = now
    else:
        target_t = last_t + dt
        if now < target_t:
            time.sleep(target_t - now)

    _test_state["last_t"] = target_t

    # Avanza fase y genera senoide
    phase = _test_state["phase"]
    phase += 2.0 * math.pi * _test_cfg["freq"] / max(1, FS)
    # Envuelve fase
    if phase > 2.0 * math.pi:
        phase -= 2.0 * math.pi
    _test_state["phase"] = phase

    val = int(round(_test_cfg["offset"] + _test_cfg["amp"] * math.sin(phase)))

    # Protección de rango 24b con signo
    if val > 0x7FFFFF:
        val = 0x7FFFFF
    elif val < -0x800000:
        val = -0x800000

    return val

# ---------------------- Autodetección de puerto ----------------------

_KNOWN_IDS = {
    (0x2341, 0x0043),  # Arduino Uno
    (0x2341, 0x0001),  # Arduino (antiguo)
    (0x2A03, 0x0043),  # Genuino/Arduino
    (0x1A86, 0x7523),  # WCH CH340
    (0x1A86, 0x5523),  # WCH CH340 variante
    (0x0403, 0x6001),  # FTDI FT232
    (0x10C4, 0xEA60),  # Silicon Labs CP210x
}
_KEYWORDS = ["arduino", "usb-serial", "ch340", "wch", "ftdi", "cp210", "nano"]
_last_known_port = None

def find_arduino_port(prefer=None):
    ports = list(list_ports.comports())
    if prefer:
        for p in ports:
            if p.device == prefer:
                return prefer
    for p in ports:
        try:
            if p.vid is not None and p.pid is not None:
                if (p.vid, p.pid) in _KNOWN_IDS:
                    return p.device
        except Exception:
            pass
    for p in ports:
        desc = f"{p.description} {p.manufacturer} {p.name}".lower()
        if any(k in desc for k in _KEYWORDS):
            return p.device
    if ports:
        return ports[0].device
    return None

# ---------------------- Serial 3B + reconexión / o Test Signal ----------------------

_ser = None
_stop_event = threading.Event()

def _open_serial():
    global _last_known_port
    port = find_arduino_port(_last_known_port)
    if port is None:
        raise RuntimeError("No se encontró ningún puerto serie compatible.")
    s = serial.Serial(port, BAUDRATE, timeout=SER_TIMEOUT)
    _last_known_port = port
    print(f"Conectado a {port} a {BAUDRATE} baudios.")
    return s

def _read_sample_24bit_be_signed(b0, b1, b2):
    raw = (b0 << 16) | (b1 << 8) | b2
    # if raw & 0x800000:
    #     raw -= 0x1000000
    return raw

def _process_value(val, cursor):
    """
    Procesa un valor: buffer memoria, WS, BPM, y DB por lotes.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    # Memoria para /ecg
    datos_ecg.append({"timestamp": ts, "value": val})

    # Empujar a WS (no bloqueante)
    try:
        ws_queue.put_nowait(val)
    except queue.Full:
        # Si se llena, descartamos lo más antiguo para mantener latencia baja
        try:
            ws_queue.get_nowait()
            ws_queue.put_nowait(val)
        except Exception:
            pass

    # BPM
    bpm_new = detectar_bpm_sencillo(val, ts)

    # Escritura por lotes unificados (no saturar SQLite)
    if activar_escritura:
        buffer_db_ecg.append((ts, val))
        if bpm_new is not None:
            buffer_db_bpm.append((ts, int(bpm_new)))
        flush_buffers_if_needed(cursor, force=False)

def _read_exact(ser, n):
    """
    Lee exactamente n bytes o devuelve None si se agota el timeout.
    """
    data = bytearray()
    while len(data) < n and not _stop_event.is_set():
        chunk = ser.read(n - len(data))
        if not chunk:  # timeout
            return None
        data.extend(chunk)
    return bytes(data)

def leer_desde_serial():
    global _ser

    cursor = db_conn.cursor()
    last_seen_switch = globals().get("DB_SWITCH_COUNTER", 0)
    while not _stop_event.is_set():
        # Modo test: genera senoide y procesa
        if _test_cfg_2["enabled"]:
            try:
# using  normalized sample
                val = gen_test_sample_normalized_2()
                _process_value(val, cursor)
            except Exception as e:
                print(f"Error generando señal de prueba: {e}")
            continue

        # Conexión/reconexión
        if _ser is None or not (_ser.is_open if not callable(getattr(_ser, "is_open", None)) else _ser.is_open()):
            try:
                _ser = _open_serial()
            except Exception as e:
                print(f"No se pudo abrir puerto: {e}. Reintentando en {RETRY_SECS}s.")
                time.sleep(RETRY_SECS)
                continue

        try:
            while not _stop_event.is_set() and _ser and (_ser.is_open if not callable(getattr(_ser, "is_open", None)) else _ser.is_open()):
                
                cur_switch = globals().get("DB_SWITCH_COUNTER", 0)
                if last_seen_switch != cur_switch:
                    try:
                        cursor = db_conn.cursor()
                    except Exception:
                        pass
                    last_seen_switch = cur_switch

                # 1) Buscar 0xAA
                b = _read_exact(_ser, 1)
                if b is None:
                    continue
                if b[0] != 0xAA:
                    continue

                # 2) Confirmar 0x55
                b = _read_exact(_ser, 1)
                if b is None or b[0] != 0x55:
                    # si no es 0x55, volvemos a buscar header
                    continue

                # 3) Leer payload de 3 bytes (MSB, MID, LSB)
                payload = _read_exact(_ser, 3)
                if payload is None or len(payload) != 3:
                    continue

                msb, mid, lsb = payload[0], payload[1], payload[2]
                val = _read_sample_24bit_be_signed(msb, mid, lsb)
                _process_value(val, cursor)

        except (serial.SerialException, OSError, ValueError) as e:
            print(f"Error de lectura serial: {e}. Intentando reconectar en {RETRY_SECS}s.")
            try:
                if _ser and (_ser.is_open if not callable(getattr(_ser, "is_open", None)) else _ser.is_open()):
                    _ser.close()
            except Exception:
                pass
            _ser = None
            time.sleep(RETRY_SECS)
            continue
        except Exception as e:
            print(f"Lectura interrumpida por excepción: {e}. Intentando reconectar en {RETRY_SECS}s.")
            try:
                if _ser and (_ser.is_open if not callable(getattr(_ser, "is_open", None)) else _ser.is_open()):
                    _ser.close()
            except Exception:
                pass
            _ser = None
            time.sleep(RETRY_SECS)
            continue

    # Cierre
    try:
        if _ser and (_ser.is_open if not callable(getattr(_ser, "is_open", None)) else _ser.is_open()):
            _ser.close()
    except Exception:
        pass
    flush_buffers_if_needed(db_conn.cursor(), force=True)
    print("Hilo de lectura finalizado.")

# ---------------------- WebSocket: broadcaster ----------------------

async def _ws_broadcaster():
    """
    Empaqueta valores en lotes y los envía a todos los clientes WS.
    Formato: texto CSV con n valores por mensaje.
    """
    BATCH = 10
    IDLE_FLUSH_MS = 50

    lote = []
    while not _stop_event.is_set():
        try:
            val = ws_queue.get(timeout=IDLE_FLUSH_MS / 1000.0)
            lote.append(val)
        except queue.Empty:
            pass

        if lote and (len(lote) >= BATCH or ws_queue.empty()):
            msg = ",".join(map(str, lote))
            for ws in list(ws_clients):
                try:
                    await ws.send_text(msg)
                except Exception:
                    try:
                        ws_clients.discard(ws)
                    except Exception:
                        pass
            lote.clear()

        await asyncio.sleep(0)

# ---------------------- FastAPI (API + WS, sin frontend) ----------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("API ECG iniciada (JSON + WebSocket). Detector: simple_threshold")
    hilo = threading.Thread(target=leer_desde_serial, daemon=True)
    hilo.start()
    ws_task = asyncio.create_task(_ws_broadcaster())
    try:
        yield
    finally:
        _stop_event.set()
        ws_task.cancel()
        try:
            await ws_task
        except Exception:
            pass
        hilo.join(timeout=2.0)
        print("API ECG detenida.")

app = FastAPI(lifespan=lifespan)

# Permitir CORS
origins = [
    "http://localhost:3000",  # tu frontend local
    "http://127.0.0.1:3000",  # alternativa 
    "https://qm1n4mn1-4321.brs.devtunnels.ms",
    "*",                       # o todos los orígenes (solo para pruebas)
]

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # <- permite todos los orígenes; para producción usa tu frontend específico
    allow_credentials=True,
    allow_methods=["*"],          # GET, POST, etc.
    allow_headers=["*"],          # Headers permitidos
)

@app.get("/health")
def health():
    return {
        "ok": True,
        "samples_in_memory": len(datos_ecg),
        "writing": activar_escritura,
        "last_known_port": _last_known_port,
        "baudrate": BAUDRATE,
        "hr_detector": "simple_threshold",
        "buffer_ecg": len(buffer_db_ecg),
        "buffer_bpm": len(buffer_db_bpm),
        "umbral": UMBRAL,
        "refract_sec": REFRACT_SEC,
        "ws_clients": len(ws_clients),
        "test_signal": _test_cfg_2
    }

@app.get("/ecg")
def obtener_ecg_memoria():
    return JSONResponse(list(datos_ecg))

@app.get("/activar_escritura/{estado}")
def activar_escritura_api(estado: str):
    global activar_escritura
    activar_escritura = (estado.lower() == "on")
    return {"escritura_activada": activar_escritura}

@app.get("/bpm")
def obtener_bpm():
    return {"bpm": _last_bpm, "timestamp": _last_bpm_ts}

@app.get("/test_signal")
def set_test_signal(
    enabled: bool = Query(..., description="true/false para activar la senoide"),
    freq: float = Query(1.0, description="Frecuencia Hz"),
    amp: int = Query(800, description="Amplitud en cuentas 24b"),
    offset: int = Query(0, description="Offset DC en cuentas 24b"),
):
    """
    Activa/desactiva modo senoide y ajusta parámetros.
    Al activarse, la lectura por serial se ignora y se envían valores senoidales a WS y DB.
    """
    _test_cfg["enabled"] = bool(enabled)
    _test_cfg["freq"] = max(0.0, float(freq))
    _test_cfg["amp"] = int(amp)
    _test_cfg["offset"] = int(offset)
    # Reset de fase/tiempo para que arranque limpio
    _test_state["phase"] = 0.0
    _test_state["last_t"] = None
    return {"ok": True, "test_signal": _test_cfg}

@app.get("/db/info")
def db_info():
    p = _current_db_path_from_conn()
    try:
        size = p.stat().st_size
        mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        size, mtime = None, None
    return {"name": p.name, "path": str(p), "size_bytes": size, "modified": mtime}

@app.post("/db/set")
def db_set(name: str = Query(..., description="Base sin .db; si existe, se autoenumera")):
    """
    Vuelca buffers, cierra la conexión actual y abre una nueva con conectar_sqlite().
    """
    global db_conn, CURRENT_DB_NAME, DB_SWITCH_COUNTER

    # Volcar buffers antes de cambiar
    try:
        flush_buffers_if_needed(db_conn.cursor(), force=True)
    except Exception:
        pass

    # Cerrar BD actual
    try:
        db_conn.close()
    except Exception:
        pass

    # Elegir nombre único y abrir
    new_db_name = _unique_db_filename(name)  # e.g., paciente.db o paciente_1.db
    db_conn = conectar_sqlite(new_db_name)
    CURRENT_DB_NAME = new_db_name

    # Avisar a hilos: renueven cursor
    DB_SWITCH_COUNTER += 1

    p = DATA_DIR / CURRENT_DB_NAME
    return {"ok": True, "db_name": CURRENT_DB_NAME, "path": str(p)}

@app.get("/db/list")
def db_list():
    """
    Lista todos los .db en DATA_DIR con tamaño y fecha.
    """
    items = []
    for p in sorted(DATA_DIR.glob("*.db")):
        try:
            size = p.stat().st_size
            mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            size, mtime = None, None
        items.append({"name": p.name, "size_bytes": size, "modified": mtime})
    return items

def _csv_stream_for_db(db_path: Path, table: str):
    # Conecta de solo lectura a la DB objetivo
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    if table == "ecg":
        yield "timestamp,value\n"
        cur.execute("SELECT timestamp, value FROM ecg_data ORDER BY id;")
    else:
        yield "timestamp,bpm\n"
        cur.execute("SELECT timestamp, bpm FROM bpm_data ORDER BY id;")

    while True:
        rows = cur.fetchmany(10000)
        if not rows:
            break
        for r in rows:
            # Campos simples, separados por coma
            yield f"{r[0]},{r[1]}\n"

    try:
        conn.close()
    except Exception:
        pass

@app.get("/db/export")
def db_export(
    name: str = Query(..., description="Nombre del archivo .db a exportar (de /db/list)"),
    table: str = Query("ecg", pattern="^(ecg|bpm)$", description="Tabla a exportar: ecg o bpm")
):
    """
    Exporta la DB indicada a CSV por streaming.
    - /db/export?name=archivo.db&table=ecg
    - /db/export?name=archivo.db&table=bpm
    """
    db_path = (DATA_DIR / name)
    if not db_path.exists() or db_path.suffix.lower() != ".db":
        return JSONResponse({"ok": False, "error": "DB no encontrada"}, status_code=404)

    # Antes de exportar, si es la BD actual, volcar buffers
    if db_path.resolve() == _current_db_path_from_conn().resolve():
        flush_buffers_if_needed(db_conn.cursor(), force=True)

    filename = f"{db_path.stem}_{table}.csv"
    return StreamingResponse(
        _csv_stream_for_db(db_path, table),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/newData")
def get_new_data():
    file_path = "newDataStatus.txt"

    try:
        with open(file_path, "r") as f:
            data = json.load(f)

        new_data_value = data.get("newData", "false").lower() == "true"

        return {"newData": new_data_value}
    except FileNotFoundError:
        return {"error":"Archivo no encontrado"}
    except json.JSONDecodeError:
        return{"error":"Error al parsear JSON"}

@app.get("/checkTrainingStatus")
def check_external():
    url = "https://qm1n4mn1-3333.brs.devtunnels.ms/"   
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return {"ok": True, "data": r.json()}  
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/predictedData")
def obtener_ecg_predicciones():
    file_path = "predicted_data.csv"
    if not os.path.exists(file_path):
        return JSONResponse({"error": "Archivo no encontrado"}, status_code=404)

    try:
        data = []
        with open(file_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                # Convertir valores a números si es necesario
                row_converted = {k: (float(v) if v.replace('.', '', 1).isdigit() else v) for k, v in row.items()}
                data.append(row_converted)

        return JSONResponse(content=data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/sendPrediction")
def send_prediction():
    file_path = "predicted_data.csv"
    if not os.path.exists(file_path):
        return JSONResponse({"error": "Archivo no encontrado"}, status_code=404)

    try:
        data = []
        with open(file_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                # Convertir valores a números si es posible
                row_converted = {
                    k: (float(v) if v.replace('.', '', 1).isdigit() else v)
                    for k, v in row.items()
                }
                data.append(row_converted)

        return {"ok": True, "predictions": data}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/doPrediction")
def do_prediction(payload: dict = Body(default={})):
    global predictionStatus
    try:
        predictionStatus = {
            "ok": True,
            "message": "Prediction sended"
        }
        return predictionStatus
    except Exception as e:
        predictionStatus = {"ok": False, "error": str(e)}
        return predictionStatus

@app.get("/predictionStatus")
def getPredictionStatus():
    return {"status": predictionStatus}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        ws_clients.discard(websocket)


@app.post("/resetPredictionStatus")
def reset_prediction_status():
    global predictionStatus
    predictionStatus = {"ok": False, "message": "idle"}
    return {"ok": True, "message": "PredictionStatus reset"}

# ---------------------- Main ----------------------

if __name__ == "__main__":
    # Ejecuta la API (JSON + WebSocket)
    uvicorn.run(app, host="0.0.0.0", port=5000)
