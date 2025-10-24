# app.py — NACH-GPT LIMS con gestión de empleados + escaneo de casos
import os
import json
import qrcode
import dropbox
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote
from flask import Flask, request, jsonify, send_from_directory, make_response, redirect

from dotenv import load_dotenv
load_dotenv()

# ---------------- CONFIG ----------------
CASES_DIR = os.getenv("BASE_ROOT", r"C:\Users\innov\Desktop\casos_descargados")
BASE_DIR = Path(__file__).parent.resolve()
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
QRS_DIR = STATIC_DIR / "qrs"
EMP_QRS_DIR = QRS_DIR / "employees"
LOG_FILE = BASE_DIR / "nachgpt_log.txt"

DROPBOX_FOLDER = os.getenv("DROPBOX_FOLDER", "/IA AUTOMATIZATION CASES DAILY")
DROPBOX_APP_KEY = os.getenv("rjq09g8c6cgpimr")
DROPBOX_APP_SECRET = os.getenv("rwko1h47pys2cnm")
DROPBOX_REFRESH_TOKEN = os.getenv("MPWwpQpd-RQAAAAAAAAAAcxPA8FJC2vrS4PjS2nRXEPiTh6Dj3jkOC76tUQd_AMB")

DROPBOX_CONFIGURED = all([DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN])

# Datos de empleados que me pasaste (ID simple, nombre, phone, pin = últimos 4)
EMPLOYEES = [
    {"id": "rajan", "name": "Dr Rajan Sheth", "phone": "6146209111"},
    {"id": "ignacio", "name": "Ignacio Ramirez", "phone": "6232310578"},
    {"id": "jonathan", "name": "Jonathan Dominguez", "phone": "6025152989"},
    {"id": "carlos", "name": "Carlos Ortiz", "phone": "6026218249"},
]
for e in EMPLOYEES:
    e["pin"] = e["phone"][-4:]

# Asegurar directorios
for p in [CASES_DIR, STATIC_DIR, QRS_DIR, EMP_QRS_DIR, TEMPLATES_DIR]:
    try:
        os.makedirs(p, exist_ok=True)
    except Exception:
        pass

app = Flask(__name__, static_folder=str(STATIC_DIR), template_folder=str(TEMPLATES_DIR))

# ---------------- UTIL ----------------
def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log(msg):
    line = f"[{now()}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def safe_name(name: str) -> str:
    return "".join(c if c not in r'<>:"/\\|?*' else "_" for c in name).strip()

def case_folder(case_name: str) -> Path:
    return Path(CASES_DIR) / safe_name(case_name)

def estado_file(folder: Path) -> Path:
    return folder / "estado.json"

def load_estado(folder: Path) -> dict:
    ef = estado_file(folder)
    if ef.exists():
        try:
            return json.loads(ef.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def write_estado(folder: Path, data: dict):
    ef = estado_file(folder)
    try:
        ef.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"⚠ Error escribiendo estado en {ef}: {e}")

def ensure_case(folder: Path, paciente_raw: str, info: dict):
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        log(f"⚠ No se puede crear carpeta (permiso): {folder}")
        return
    instr = folder / "INSTRUCCIONES.txt"
    if not instr.exists():
        txt = f"ORDEN DE TRABAJO\nPACIENTE: {paciente_raw}\nCREADO: {now()}\n\nNOTAS:\n{info.get('notas','')}\n"
        try:
            instr.write_text(txt, encoding="utf-8")
        except Exception as e:
            log(f"⚠ Error creando INSTRUCCIONES.txt en {instr}: {e}")
    estado = load_estado(folder)
    if not estado:
        estado = {"created_at": now(), "events": [], "current_phase": "RECIBIDO"}
    write_estado(folder, estado)

def qr_path_for(folder: Path) -> Path:
    return QRS_DIR / f"{folder.name}.png"

def generate_case_qr(folder: Path):
    try:
        url = f"http://{os.getenv('HOST','127.0.0.1')}:{os.getenv('PORT','8000')}/case_track/{quote(folder.name)}"
        img = qrcode.make(url)
        out = qr_path_for(folder)
        img.save(out)
        log(f"QR Caso generado: {out}")
        return out
    except Exception as e:
        log(f"⚠ Error generando QR para {folder}: {e}")

def generate_employee_qr(emp):
    try:
        # QR que apunta a /set_emp/<id>/<pin> (el empleado lo escanea para "loguearse")
        url = f"http://{os.getenv('HOST','127.0.0.1')}:{os.getenv('PORT','8000')}/set_emp/{emp['id']}/{emp['pin']}"
        img = qrcode.make(url)
        out = EMP_QRS_DIR / f"{emp['id']}.png"
        img.save(out)
        return out
    except Exception as e:
        log(f"⚠ Error generando QR empleado {emp['id']}: {e}")

def get_dropbox_client():
    if not DROPBOX_CONFIGURED:
        return None
    try:
        dbx = dropbox.Dropbox(
            oauth2_refresh_token=DROPBOX_REFRESH_TOKEN,
            app_key=DROPBOX_APP_KEY,
            app_secret=DROPBOX_APP_SECRET,
        )
        dbx.users_get_current_account()
        return dbx
    except Exception as e:
        log(f"⚠ Dropbox connection error: {e}")
        return None

def upload_to_dropbox(local_path: Path, dropbox_path: str):
    if not DROPBOX_CONFIGURED:
        return False
    dbx = get_dropbox_client()
    if not dbx:
        return False
    try:
        with open(local_path, "rb") as f:
            dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.overwrite)
        log(f"☁ Subido a Dropbox: {dropbox_path}")
        return True
    except Exception as e:
        log(f"⚠ Error subiendo a Dropbox: {e}")
        return False

def sync_case_to_dropbox(folder: Path):
    if not DROPBOX_CONFIGURED:
        log("❌ Dropbox no configurado - omitiendo sync")
        return
    dbx = get_dropbox_client()
    if not dbx:
        return
    for f in folder.glob("*"):
        if f.is_file():
            remote = f"{DROPBOX_FOLDER}/{folder.name}/{f.name}"
            upload_to_dropbox(f, remote)

def add_event(folder: Path, phase: str, worker: str, note: str):
    estado = load_estado(folder)
    ev = {"ts": now(), "phase": phase, "worker": worker, "note": note}
    estado.setdefault("events", []).append(ev)
    estado["current_phase"] = phase
    write_estado(folder, estado)
    log(f"Evento: {folder.name} | {phase} | {worker}")
    return ev

# Generar QR empleados al inicio
for emp in EMPLOYEES:
    generate_employee_qr(emp)

# ---------------- RUTAS ----------------

# Sirve index.html tal cual (no pasar por Jinja para evitar conflictos con {{ }} en JS)
@app.route("/")
def index():
    return send_from_directory(str(TEMPLATES_DIR), "index.html")

# Página con los QR de empleados listos para abrir/imprimir
@app.route("/local_auto_qr")
def local_auto_qr():
    # Serve the employee qrs page (a simple generated HTML)
    rows = []
    for emp in EMPLOYEES:
        img_path = f"/static/qrs/employees/{emp['id']}.png"
        rows.append(f"<div style='margin:12px;display:inline-block;text-align:center'><img src='{img_path}' style='width:160px;height:160px;border:4px solid #d4af37;border-radius:8px'><div style='margin-top:8px'><b>{emp['name']}</b><div style='font-size:12px;color:#ddd'>PIN: {emp['pin']}</div></div></div>")
    html = "<!doctype html><html><head><meta charset='utf-8'><title>QR Empleados</title></head><body style='background:#111;color:#fff;font-family:Arial;padding:18px'><h2 style='color:#ffd700'>QR Empleados</h2><div>"+ "".join(rows) + "</div><p style='color:#999;margin-top:18px'>Escanea tu QR para iniciar sesión de trabajo (el QR ya contiene tu PIN).</p></body></html>"
    return html

# Listado de casos (para la UI)
@app.route("/cases")
def api_cases():
    items = []
    base = Path(CASES_DIR)
    if not base.exists():
        return jsonify(cases=[])
    for p in sorted(base.iterdir(), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True):
        if not p.is_dir(): continue
        estado = load_estado(p)
        qr_exists = (QRS_DIR / f"{p.name}.png").exists()
        items.append({
            "name": p.name,
            "path": str(p),
            "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "qr_url": f"/static/qrs/{p.name}.png" if qr_exists else "",
            "phase": estado.get("current_phase","RECIBIDO"),
            "events_count": len(estado.get("events", [])),
            "last_updated": estado.get("created_at", "")
        })
    return jsonify(cases=items)

# Crear nuevo caso (soporta archivos)
@app.route("/new_case", methods=["POST"])
def api_new_case():
    paciente = request.form.get("paciente", "").strip()
    notas = request.form.get("notas", "")
    if not paciente:
        return jsonify({"ok": False, "msg": "Paciente requerido"}), 400
    folder = case_folder(paciente)
    ensure_case(folder, paciente, {"notas": notas})
    # archivos
    archivos = request.files.getlist("archivos")
    for archivo in archivos:
        if archivo and archivo.filename:
            archivo.save(folder / safe_name(archivo.filename))
            log(f"Archivo guardado: {archivo.filename}")
    # qr
    generate_case_qr(folder)
    add_event(folder, "RECIBIDO", "sistema", "Caso creado manualmente con adjuntos")
    # sync dropbox (intentar)
    if DROPBOX_CONFIGURED:
        try:
            sync_case_to_dropbox(folder)
        except Exception as e:
            log(f"⚠ Error sincronizando con Dropbox: {e}")
    return jsonify({"ok": True, "path": str(folder)})

# Endpoint que el QR del empleado apunta a: setea cookie emp_id si PIN coincide
@app.route("/set_emp/<emp_id>/<pin>")
def set_emp(emp_id, pin):
    emp = next((e for e in EMPLOYEES if e["id"] == emp_id), None)
    if not emp:
        return "Empleado no encontrado", 404
    if pin != emp["pin"]:
        return "PIN inválido", 403
    resp = make_response(redirect("/scan_ready"))
    # cookie simple para identificar empleado en próximas peticiones de escaneo
    resp.set_cookie("emp_id", emp_id, max_age=60*60*8)  # 8 horas
    return resp

# Página que ve el empleado tras escanear su QR
@app.route("/scan_ready")
def scan_ready():
    emp_id = request.cookies.get("emp_id")
    if not emp_id:
        return redirect("/local_auto_qr")
    emp = next((e for e in EMPLOYEES if e["id"] == emp_id), None)
    if not emp:
        return redirect("/local_auto_qr")
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Listo para escanear</title></head><body style='background:#111;color:#fff;font-family:Arial;padding:18px'>
    <h2 style='color:#ffd700'>Hola, {emp['name']}</h2>
    <p>Ahora escanea el <b>QR del caso</b>. El sistema registrará automáticamente que <b>{emp['name']}</b> tomó el caso.</p>
    <p>Si tu celular lo permite, simplemente apunta la cámara al QR del caso (apunta a la URL del QR).</p>
    <p style='margin-top:18px'><a href='/' style='color:#90ee90'>Volver al panel</a></p>
    </body></html>"""
    return html

# Endpoint al que apuntan los QR de cada caso: registra el escaneo con empleado si cookie emp_id existe
@app.route("/case_track/<path:case_name>")
def case_track(case_name):
    case_name = unquote(case_name)
    folder = case_folder(case_name)
    if not folder.exists():
        return f"<h3>El caso {case_name} no existe.</h3>", 404
    emp_id = request.cookies.get("emp_id")
    phase = request.args.get("phase", "EN PROCESO")
    note = request.args.get("note", "")
    if emp_id:
        emp = next((e for e in EMPLOYEES if e["id"] == emp_id), None)
        worker = emp["name"] if emp else emp_id
        add_event(folder, phase, worker, f"Registro por escaneo (nota: {note})")
        # intentar sync parcial con dropbox tras evento (opcional)
        if DROPBOX_CONFIGURED:
            try:
                sync_case_to_dropbox(folder)
            except Exception as e:
                log(f"⚠ Error sync después de track: {e}")
        return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Registro</title></head>
        <body style='background:#111;color:#fff;font-family:Arial;padding:18px'><h2 style='color:#ffd700'>Registrado</h2>
        <p>El caso <b>{case_name}</b> fue registrado como <b>{phase}</b> por <b>{worker}</b> a las {now()}.</p>
        <p><a href='/'>Volver al panel</a></p>
        </body></html>"""
    else:
        # Si no hay empleado logueado, pedir que primero se identifique (o dar instrucción)
        return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Escanear</title></head>
        <body style='background:#111;color:#fff;font-family:Arial;padding:18px'><h2 style='color:#ffd700'>Identificación requerida</h2>
        <p>No se detectó identificación de empleado. Escanea primero tu <b>QR de empleado</b> desde <a href='/local_auto_qr' style='color:#90ee90'>esta página</a> para iniciar sesión y luego vuelve a escanear el QR del caso.</p>
        </body></html>"""

# print orden de trabajo con QR
@app.route("/print_order/<path:case_name>")
def print_order(case_name):
    case_name = unquote(case_name)
    folder = case_folder(case_name)
    if not folder.exists():
        return "Caso no encontrado", 404
    instr = (folder / "INSTRUCCIONES.txt").read_text(encoding="utf-8") if (folder / "INSTRUCCIONES.txt").exists() else ""
    qr_rel = f"/static/qrs/{folder.name}.png" if (QRS_DIR / f"{folder.name}.png").exists() else ""
    html = "<!doctype html><html><head><meta charset='utf-8'><title>Orden</title></head><body style='font-family:Arial;padding:18px'>"
    html += f"<h2>Orden de trabajo — {case_name}</h2>"
    html += "<pre style='background:#f7f7f7;padding:12px;border-radius:6px'>{}</pre>".format(instr)
    if qr_rel:
        html += f"<div style='margin-top:12px'><img src='{qr_rel}' style='width:220px;height:220px'></div>"
    html += "<div style='margin-top:12px'><button onclick='window.print()'>Imprimir</button></div>"
    html += "</body></html>"
    return html

# Upload manual en página caso (subir archivo a caso existente)
@app.route("/upload_file", methods=["POST"])
def upload_file():
    file = request.files.get("file")
    case_name = request.form.get("case_name")
    if not file or not case_name:
        return jsonify({"ok": False, "msg": "Archivo o caso faltante"}), 400
    folder = case_folder(case_name)
    if not folder.exists():
        return jsonify({"ok": False, "msg": "Caso no encontrado"}), 404
    dest = folder / safe_name(file.filename)
    try:
        file.save(dest)
        log(f"Archivo guardado en {dest}")
        if DROPBOX_CONFIGURED:
            sync_case_to_dropbox(folder)
        return jsonify({"ok": True})
    except Exception as e:
        log(f"⚠ Error subiendo archivo {file.filename}: {e}")
        return jsonify({"ok": False, "msg": str(e)}), 500

# abrir carpeta en PC
@app.route("/open_folder", methods=["POST"])
def open_folder():
    data = request.get_json(force=True, silent=True) or {}
    path = data.get("path")
    if not path or not Path(path).exists():
        return jsonify({"ok": False, "msg": "path not found"}), 404
    try:
        if os.name == "nt":
            os.startfile(path)
            return jsonify({"ok": True})
        return jsonify({"ok": False, "msg": "only Windows supported"}), 400
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

# logs
@app.route("/logs")
def logs():
    if not Path(LOG_FILE).exists():
        return jsonify({"lines": []})
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()[-300:]
    return jsonify({"lines": [l.strip() for l in lines]})

# servir qrs (caso)
@app.route("/static/qrs/<path:filename>")
def serve_qr(filename):
    return send_from_directory(str(QRS_DIR), filename)

# servir qrs empleados
@app.route("/static/qrs/employees/<path:filename>")
def serve_emp_qr(filename):
    return send_from_directory(str(EMP_QRS_DIR), filename)

# borrar caso
@app.delete("/case/<path:case_name>")
def delete_case(case_name):
    case_name = unquote(case_name)
    folder = case_folder(case_name)
    if not folder.exists():
        return jsonify({"ok": False, "msg": "no existe"}), 404
    try:
        shutil.rmtree(folder)
    except Exception as e:
        log(f"⚠ Error borrando carpeta {folder}: {e}")
        return jsonify({"ok": False, "msg": "error borrando carpeta"}), 500
    qr = QRS_DIR / f"{folder.name}.png"
    try:
        if qr.exists(): qr.unlink()
    except Exception:
        pass
    log(f"Caso eliminado: {case_name}")
    return jsonify({"ok": True})
# ============================================================
# 🚀 Arranque del servidor NACH-GPT LIMS
# ============================================================

# 🔄 Sincronización inicial de Dropbox (solo en local)
if not os.getenv("RENDER"):  # Render define esta variable automáticamente
    if DROPBOX_CONFIGURED:
        log("📤 Subiendo casos locales a Dropbox...")
        try:
            sync_local_to_dropbox()
            log("✅ Sincronización inicial con Dropbox completada.")
        except Exception as e:
            log(f"⚠️ Error al sincronizar con Dropbox: {e}")
    else:
        log("⚠️ Dropbox no está configurado. Se omite la sincronización inicial.")

if __name__ == "__main__":
    log("Arrancando NACH-GPT LIMS (con soporte de empleados/escaneo)")
    log(f"Directorios: CASES_DIR={CASES_DIR}")
    log(f"Dropbox configurado: {DROPBOX_CONFIGURED}")

    # Solo mostrar diagnóstico de Dropbox en entorno local
    if not os.getenv("RENDER"):
        log("===== DIAGNÓSTICO DROPBOX =====")
        log(f"App Key: {os.getenv('DROPBOX_APP_KEY', 'no encontrada')}")
        log(f"App Secret: {'***' if os.getenv('DROPBOX_APP_SECRET') else 'no encontrada'}")
        log(f"Refresh Token: {'***' if os.getenv('DROPBOX_REFRESH_TOKEN') else 'no encontrada'}")
        log(f"Carpeta de Dropbox: {os.getenv('DROPBOX_FOLDER', 'no encontrada')}")
        log(f"Dropbox configurado: {DROPBOX_CONFIGURED}")
        log("================================")

    # generar QR de casos existentes si faltan
    for p in Path(CASES_DIR).glob("*"):
        if p.is_dir():
            if not (QRS_DIR / f"{p.name}.png").exists():
                try:
                    generate_case_qr(p)
                except Exception as e:
                    log(f"Error generando QR para {p.name}: {e}")

    port = int(os.environ.get("PORT", 8000))
    log(f"Iniciando servidor Flask en 0.0.0.0:{port}...")
    app.run(host="0.0.0.0", port=port)
