import sys
import os
import json
import uuid
import queue
import threading
import tempfile
import webbrowser
import time

from flask import Flask, request, jsonify, Response, send_file, render_template

from core.downloader import run_download
from core.road_direction import process_to_zip
from core.statistics import generate_stats

# ---------------------------------------------------------------------------
# Path helpers (works both in dev and PyInstaller --onefile)
# ---------------------------------------------------------------------------

def _base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _base_dir()
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder='templates')
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024  # 64 MB upload limit

# Active download tasks: task_id -> {"queue": Queue, "stop": Event}
_tasks: dict = {}
_tasks_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    'api_keys': [],
    'settings': {
        'fovy': 85, 'quality': 100, 'pitch': 0,
        'width': 800, 'height': 400,
    },
    'year_option': 0,
    'selected_years': '',
    'directions': ['F', 'B', 'L', 'R'],
}


def _load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding='utf-8') as f:
                data = json.load(f)
            # Merge with defaults so new keys always exist
            cfg = dict(DEFAULT_CONFIG)
            cfg.update(data)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def _save_config(data):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(_load_config())


@app.route('/api/config', methods=['POST'])
def save_config():
    data = request.get_json(force=True)
    _save_config(data)
    return jsonify({'ok': True})


# --- Download ---

@app.route('/api/download/start', methods=['POST'])
def download_start():
    params = request.get_json(force=True)

    # Basic validation
    required = ('csv_path', 'save_path', 'api_keys')
    for key in required:
        if not params.get(key):
            return jsonify({'error': f'缺少参数: {key}'}), 400
    if not os.path.isfile(params['csv_path']):
        return jsonify({'error': f'CSV 文件不存在: {params["csv_path"]}'}), 400

    task_id = uuid.uuid4().hex[:8]
    q = queue.Queue()
    stop_event = threading.Event()

    with _tasks_lock:
        _tasks[task_id] = {'queue': q, 'stop': stop_event}

    t = threading.Thread(target=run_download, args=(params, q, stop_event), daemon=True)
    t.start()

    return jsonify({'task_id': task_id})


@app.route('/api/download/stream')
def download_stream():
    task_id = request.args.get('task_id', '')
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404

    q = task['queue']

    def generate():
        while True:
            try:
                msg = q.get(timeout=30)
            except queue.Empty:
                yield 'data: {"type":"ping"}\n\n'
                continue
            if msg is None:
                yield 'data: __DONE__\n\n'
                with _tasks_lock:
                    _tasks.pop(task_id, None)
                break
            yield f'data: {json.dumps(msg, ensure_ascii=False)}\n\n'

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/api/download/stop', methods=['POST'])
def download_stop():
    task_id = request.get_json(force=True).get('task_id', '')
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task:
        task['stop'].set()
    return jsonify({'ok': True})


# --- Road direction ---

@app.route('/api/road_direction', methods=['POST'])
def road_direction():
    if 'shp' not in request.files:
        return jsonify({'error': '请上传 .shp 文件'}), 400

    with tempfile.TemporaryDirectory() as tmpdir:
        # Save all uploaded shapefile components
        shp_path = None
        for key in ('shp', 'shx', 'dbf', 'prj', 'cpg'):
            f = request.files.get(key)
            if f:
                dest = os.path.join(tmpdir, f'input.{key}')
                f.save(dest)
                if key == 'shp':
                    shp_path = dest

        if not shp_path:
            return jsonify({'error': '未找到 .shp 文件'}), 400

        try:
            zip_bytes = process_to_zip(shp_path)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    return Response(
        zip_bytes,
        mimetype='application/zip',
        headers={'Content-Disposition': 'attachment; filename=road_direction_result.zip'}
    )


# --- Statistics ---

@app.route('/api/statistics', methods=['POST'])
def statistics():
    data = request.get_json(force=True)
    csv_path     = data.get('csv_path', '')
    images_folder = data.get('images_folder', '')

    if not os.path.isfile(csv_path):
        return jsonify({'error': f'CSV 文件不存在: {csv_path}'}), 400
    if not os.path.isdir(images_folder):
        return jsonify({'error': f'图片文件夹不存在: {images_folder}'}), 400

    with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as tmp:
        out_path = tmp.name

    try:
        generate_stats(csv_path, images_folder, out_path)
        return send_file(out_path, mimetype='text/csv',
                         as_attachment=True, download_name='statistics.csv')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- Path picker (uses tkinter on the server side) ---

@app.route('/api/pick_path')
def pick_path():
    mode = request.args.get('mode', 'dir')  # 'dir' or 'csv'
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', True)
        if mode == 'csv':
            path = filedialog.askopenfilename(
                title='选择坐标 CSV 文件',
                filetypes=[('CSV 文件', '*.csv'), ('所有文件', '*.*')]
            )
        else:
            path = filedialog.askdirectory(title='选择文件夹')
        root.destroy()
        return jsonify({'path': path or ''})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- Image preview ---

@app.route('/api/images/list')
def images_list():
    folder = request.args.get('folder', '')
    if not os.path.isdir(folder):
        return jsonify({'error': '文件夹不存在'}), 400
    exts = {'.jpg', '.jpeg', '.png'}
    files = sorted(
        f for f in os.listdir(folder)
        if os.path.splitext(f)[1].lower() in exts
    )
    return jsonify({'files': files, 'folder': folder})


@app.route('/api/images/file')
def images_file():
    path = request.args.get('path', '')
    if not os.path.isfile(path):
        return jsonify({'error': '文件不存在'}), 404
    return send_file(path)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    os.environ['NO_PROXY'] = 'mapsv0.bdimg.com'

    port = 5731
    url = f'http://127.0.0.1:{port}'

    if getattr(sys, 'frozen', False):
        # Suppress werkzeug banner in packaged exe
        import logging
        logging.getLogger('werkzeug').setLevel(logging.ERROR)

    def _open_browser():
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=_open_browser, daemon=True).start()
    print(f'SV_collect 已启动: {url}')
    app.run(host='127.0.0.1', port=port, debug=False, threaded=True)
