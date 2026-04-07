import os
import json
import requests
import time
import csv
import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

os.environ['NO_PROXY'] = 'mapsv0.bdimg.com'

HEADER = {'User-Agent': 'Mozilla/5.0'}
URL_QSDATA = 'https://mapsv0.bdimg.com/?qt=qsdata&x={}&y={}'
URL_SDATA  = 'https://mapsv0.bdimg.com/?qt=sdata&sid={}&pc=1'
URL_IMAGE  = 'https://mapsv0.bdimg.com/?qt=pr3d&fovy={fovy}&quality={quality}&panoid={panoid}&heading={heading}&pitch={pitch}&width={width}&height={height}'
URL_GEOCONV = 'http://api.map.baidu.com/geoconv/v1/?coords={},{}&from=1&to=6&ak={}'

DIRECTION_MAP = {
    'F': 0,
    'L': 90,
    'B': 180,
    'R': 270,
}


def _log(q, text):
    ts = datetime.now().strftime('%H:%M:%S')
    q.put({'type': 'log', 'text': f'[{ts}] {text}'})


def _progress(q, done, total):
    q.put({'type': 'progress', 'done': done, 'total': total})


def read_csv_coords(csv_path):
    """Read CSV with columns: pointID, lng, lat, direction"""
    points = []
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            points.append({
                'pointID': row['pointID'],
                'lng': float(row['lng']),
                'lat': float(row['lat']),
                'direction': float(row.get('direction', 0)),
            })
    return points


def _convert_coord(x, y, api_keys, key_state, q):
    """
    Convert WGS84 to BD09 via Baidu API.
    key_state: dict with 'index' (current key index) and 'exhausted' (set of exhausted key indices)
    Returns (lng, lat) or None. Raises RuntimeError if all keys are exhausted.
    """
    n = len(api_keys)
    tried = 0
    while tried < n * 2:
        idx = key_state['index']
        if idx in key_state['exhausted']:
            # skip exhausted key
            key_state['index'] = (idx + 1) % n
            tried += 1
            if len(key_state['exhausted']) >= n:
                raise RuntimeError('ALL_KEYS_EXHAUSTED')
            continue
        try:
            url = URL_GEOCONV.format(x, y, api_keys[idx])
            r = requests.get(url, headers=HEADER, verify=False, timeout=10)
            data = r.json()
            status = data.get('status', -1)
            if status == 302 or status == 230:
                # 302 = quota exceeded, 230 = invalid key
                _log(q, f'⚠️  API Key [{api_keys[idx][:8]}...] 已达到配额上限或无效，切换下一个')
                key_state['exhausted'].add(idx)
                key_state['index'] = (idx + 1) % n
                if len(key_state['exhausted']) >= n:
                    raise RuntimeError('ALL_KEYS_EXHAUSTED')
                tried += 1
                continue
            lng = data['result'][0]['x']
            lat = data['result'][0]['y']
            return lng, lat
        except RuntimeError:
            raise
        except Exception:
            key_state['index'] = (idx + 1) % n
            time.sleep(3)
            tried += 1
    return None


def _get_panoid(bd_lng, bd_lat):
    """Query street view availability. Returns panoid string or None."""
    try:
        r = requests.get(URL_QSDATA.format(bd_lng, bd_lat), headers=HEADER, verify=False, timeout=10)
        data = r.json()
        return data['content']['id']
    except Exception:
        return None


def _get_timeline(panoid):
    """Get available years and IDs for a panoid. Returns list of (id, year)."""
    for _ in range(3):
        try:
            r = requests.get(URL_SDATA.format(panoid), headers=HEADER, verify=False, timeout=10)
            data = r.json()
            timeline = data['content'][0]['TimeLine']
            return [(t['ID'], t['Year']) for t in timeline]
        except Exception:
            time.sleep(5)
    return []


def _download_image(panoid, heading, settings, filename):
    """Download a single street view image."""
    url = URL_IMAGE.format(
        fovy=settings['fovy'], quality=settings['quality'],
        panoid=panoid, heading=heading, pitch=settings['pitch'],
        width=settings['width'], height=settings['height']
    )
    r = requests.get(url, headers=HEADER, verify=False, timeout=15)
    with open(filename, 'wb') as f:
        f.write(r.content)


def _heading_for_direction(base_direction, dir_key):
    """Calculate absolute heading from road direction and view direction."""
    offset = DIRECTION_MAP[dir_key]
    return (base_direction + offset) % 360


def run_download(params, q, stop_event):
    """
    Main download worker. Runs in a background thread.
    params keys: csv_path, save_path, api_keys, settings,
                 year_option (0=all,1=latest,2=custom), selected_years,
                 directions (list of 'F','L','B','R')
    """
    csv_path     = params['csv_path']
    save_path    = params['save_path']
    api_keys     = params['api_keys']
    settings     = params['settings']
    year_option  = params['year_option']
    selected_years = set(params.get('selected_years', []))
    directions   = params['directions']

    try:
        points = read_csv_coords(csv_path)
    except Exception as e:
        _log(q, f'读取 CSV 失败: {e}')
        q.put(None)
        return

    total = len(points)
    done_count = 0
    no_sv_count = 0
    # key_state is shared across threads — use a lock for safe mutation
    key_state = {'index': 0, 'exhausted': set()}
    key_state_lock = threading.Lock()

    os.makedirs(save_path, exist_ok=True)
    _log(q, f'共 {total} 个点位，使用 {len(api_keys)} 个 API Key，开始处理...')
    _log(q, f'提示：每个百度 API Key 坐标转换限额约 5000 次/天，{len(api_keys)} 个 Key 可支撑约 {len(api_keys)*5000} 个点位')
    _progress(q, 0, total)

    def process_point(pt):
        nonlocal done_count, no_sv_count
        if stop_event.is_set():
            return

        pid = pt['pointID']
        lng, lat = pt['lng'], pt['lat']
        base_dir = pt['direction']

        # Convert coordinates
        try:
            with key_state_lock:
                bd = _convert_coord(lng, lat, api_keys, key_state, q)
        except RuntimeError:
            _log(q, '❌ 所有 API Key 配额已耗尽，任务终止。请添加新的 API Key 后重新运行（已下载的图片不会重复下载）。')
            stop_event.set()
            done_count += 1
            _progress(q, done_count, total)
            return

        if bd is None:
            _log(q, f'点位 {pid}: 坐标转换失败，跳过')
            done_count += 1
            _progress(q, done_count, total)
            return

        bd_lng, bd_lat = bd
        panoid = _get_panoid(bd_lng, bd_lat)
        if panoid is None:
            _log(q, f'点位 {pid}: 无街景数据')
            no_sv_count += 1
            done_count += 1
            _progress(q, done_count, total)
            return

        timeline = _get_timeline(panoid)
        if not timeline:
            _log(q, f'点位 {pid}: 获取时间线失败')
            done_count += 1
            _progress(q, done_count, total)
            return

        # Filter by year option
        if year_option == 1:
            max_year = max(y for _, y in timeline)
            to_download = [(i, y) for i, y in timeline if y == max_year][:1]
        elif year_option == 2:
            to_download = [(i, y) for i, y in timeline if y in selected_years]
        else:
            to_download = list(timeline)

        for img_id, year in to_download:
            if stop_event.is_set():
                return
            for dir_key in directions:
                heading = _heading_for_direction(base_dir, dir_key)
                filename = os.path.join(save_path, f'{year}_{int(float(pid))}_{dir_key}.jpg')
                if os.path.exists(filename):
                    continue  # resume: skip already downloaded
                try:
                    time.sleep(0.5)
                    _download_image(img_id, heading, settings, filename)
                    _log(q, f'已保存: {os.path.basename(filename)}')
                except Exception as e:
                    _log(q, f'点位 {pid} {year} {dir_key} 下载失败: {e}')

        done_count += 1
        _progress(q, done_count, total)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(process_point, pt) for pt in points]
        for f in as_completed(futures):
            if stop_event.is_set():
                break
            try:
                f.result()
            except Exception as e:
                _log(q, f'线程异常: {e}')

    _log(q, f'完成！共 {total} 个点，无街景 {no_sv_count} 个，有街景 {total - no_sv_count} 个')
    q.put(None)  # sentinel
