#!/usr/bin/env python3
"""TimelineLapse: local screenshot sessions + FFmpeg timelapse export. No pip deps."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import mimetypes
from pathlib import Path
import secrets
import shutil
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote
import webbrowser
import zipfile

ROOT = Path(__file__).resolve().parent
DATA = ROOT / '.timelinelapse'
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
JOBS = {}
POOL = ThreadPoolExecutor(max_workers=1)
VERSION = '0.1.0'


def text(value, limit=64):
    return ' '.join(str(value or '').split())[:limit]


def number(value, lo, hi):
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValueError('Valor numérico inválido.') from None
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'El valor debe estar entre {lo} y {hi}.')
    return value


def folder_for(key):
    if key == 'demo':
        return ROOT / 'assets' / 'demo'
    if len(key) != 24 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('Sesión inválida.')
    return DATA / key


def session(key):
    p = folder_for(key) / 'session.json'
    if not p.is_file():
        raise ValueError('No se encontró la sesión.')
    return json.loads(p.read_text(encoding='utf-8'))


def save_session(data):
    folder = folder_for(data['id'])
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / 'session.tmp'
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary.replace(folder / 'session.json')


def new_session(title, interval):
    data = {'id': secrets.token_hex(12), 'title': text(title, 48) or 'Mi edición',
            'interval': number(interval, .5, 300), 'created': time.time(), 'elapsed': 0,
            'frames': [], 'demo': False, 'skipped': 0}
    save_session(data)
    return data


def jpeg_size(data):
    """Read baseline/progressive JPEG dimensions without third-party packages."""
    if not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
        raise ValueError('La captura no es una imagen JPEG completa.')
    i = 2
    while i + 4 < len(data):
        if data[i] != 255:
            raise ValueError('JPEG inválido.')
        while i < len(data) and data[i] == 255:
            i += 1
        marker = data[i]
        i += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        length = struct.unpack('>H', data[i:i+2])[0]
        if length < 2 or i + length > len(data):
            raise ValueError('JPEG inválido.')
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack('>HH', data[i+3:i+7])
            if not 32 <= width <= 7680 or not 32 <= height <= 4320:
                raise ValueError('El recorte debe medir entre 32×32 y 7680×4320 píxeles.')
            return width, height
        i += length
    raise ValueError('No se pudieron leer las dimensiones JPEG.')


def add_frame(key, image, elapsed):
    if key == 'demo':
        raise ValueError('La demo es de solo lectura.')
    width, height = jpeg_size(image)
    elapsed = number(elapsed, 0, 86400*365)
    with LOCK:
        data = session(key)
        if data['frames'] and (width != data['width'] or height != data['height']):
            raise ValueError('Cambió el tamaño del recorte. Iniciá otra sesión para cambiarlo.')
        if elapsed < data['elapsed']:
            raise ValueError('El tiempo de las capturas debe ser creciente.')
        if len(data['frames']) >= 100000:
            raise ValueError('La sesión alcanzó 100.000 capturas. Iniciá una nueva.')
        name = f'{len(data["frames"]):06d}.jpg'
        frames = folder_for(key) / 'frames'
        frames.mkdir(exist_ok=True)
        (frames / name).write_bytes(image)
        data.update(width=width, height=height, elapsed=elapsed)
        data['frames'].append({'file': name, 'elapsed': round(elapsed, 3)})
        save_session(data)
    return len(data['frames'])


def render(key, opts, output_dir, progress=None):
    with LOCK:
        data = session(key)
    count = len(data['frames'])
    if count < 2:
        raise ValueError('Necesitás al menos dos capturas para crear el timelapse.')
    if not shutil.which('ffmpeg'):
        raise ValueError('Instalá FFmpeg y volvé a abrir TimelineLapse para exportar MP4.')
    duration = number(opts.get('duration', 12), 2, 120)
    hold = number(opts.get('hold', 1), 0, 5)
    fmt = opts.get('format', 'landscape')
    if fmt not in ('landscape', 'portrait', 'native'):
        raise ValueError('Formato inválido.')
    title = text(opts.get('title', data['title']), 32)
    frames_path = folder_for(key) / 'frames'
    output_dir.mkdir(parents=True, exist_ok=True)
    # Each retained capture gets equal screen time. The final frame holds separately.
    framerate = count / duration
    # Browser JPEGs are full-range. Explicitly convert to limited-range SDR for MP4 players.
    filters = ['setsar=1', 'scale=in_range=pc:out_range=tv', 'format=yuv420p', 'setparams=range=limited']
    if fmt == 'native':
        filters += ["scale=w='min(iw,1920)':h='min(ih,1080)':force_original_aspect_ratio=decrease:force_divisible_by=2"]
    else:
        w, h = (1920, 1080) if fmt == 'landscape' else (1080, 1920)
        image_w, image_h = (1792, 720) if fmt == 'landscape' else (1000, 1080)
        image_y = 240 if fmt == 'landscape' else 420
        filters += [f'scale={image_w}:{image_h}:force_original_aspect_ratio=decrease:force_divisible_by=2',
                    f'pad={w}:{h}:(ow-iw)/2:{image_y}+({image_h}-ih)/2:color=0x111412']
        if opts.get('titles', True):
            shutil.copy(ROOT / 'assets' / 'SpaceGrotesk.ttf', output_dir / 'font.ttf')
            elapsed = data.get('elapsed', 0)
            hours, minutes = int(elapsed)//3600, int(elapsed)%3600//60
            time_label = f'{hours}h {minutes:02d}m' if hours else f'{minutes} min'
            if elapsed < 60:
                time_label = f'{round(elapsed)} s'
            lines = {'title': title, 'kicker': 'THE MAKING OF AN EDIT',
                     'stats': f'{time_label} / {count} captures',
                     'disclosure': 'ILLUSTRATIVE DEMO' if data.get('demo') else ''}
            for name, value in lines.items():
                (output_dir / f'{name}.txt').write_text(value, encoding='utf-8')
            def draw(name, x, y, size, color):
                return (f'drawtext=fontfile=font.ttf:textfile={name}.txt:expansion=none:'
                        f'x={x}:y={y}:fontsize={size}:fontcolor={color}')
            advance = sum(.98 if c in 'MWmw@' else .78 if c.isupper() else .34 if c in " ilt.,:!'" else .66 for c in title)
            title_size = min(58 if fmt == 'landscape' else 46, int((w-128)/max(1,advance)))
            filters += [draw('kicker',64,70,22,'0xc9e991'),
                        draw('title',64,120,title_size,'0xf3f3e9'),
                        draw('stats',64,h-70,24,'0x9aada1'),
                        draw('disclosure',64,h-110,18,'0x9aada1')]
    filters += [f'tpad=stop_mode=clone:stop_duration={hold}', 'fps=30', 'format=yuv420p']
    out = output_dir / 'timelinelapse.mp4'
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
           '-framerate', str(framerate), '-start_number', '0', '-i', str((frames_path/'%06d.jpg').resolve()),
           # Freeze input length when a session continues recording during an export.
           '-vf', f'trim=end_frame={count},' + ','.join(filters),
           '-t', str(duration+hold), '-an', '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
           '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-color_primaries', 'bt709',
           '-color_trc', 'bt709', '-colorspace', 'bt709', '-movflags', '+faststart',
           '-progress', 'pipe:1', '-nostats', str(out.resolve())]
    with (output_dir / 'render.log').open('w') as log:
        process = subprocess.Popen(cmd, cwd=output_dir, stdout=subprocess.PIPE, stderr=log, text=True)
        for line in process.stdout:
            if line.startswith('out_time_us=') and progress:
                try:
                    progress(min(99, max(0, int(int(line.strip().split('=')[1])/(duration+hold)/1e4))))
                except ValueError:
                    pass
        process.stdout.close()
        process.wait()
    if process.returncode:
        raise ValueError('Falló FFmpeg: ' + (output_dir/'render.log').read_text()[-1800:])
    return out


def render_job(job, key, opts):
    def update(**values):
        with LOCK:
            JOBS[job].update(values)
    try:
        update(status='rendering')
        out = render(key, opts, DATA/'exports'/job, lambda p: update(progress=p))
        update(status='ready', progress=100, download=f'/exports/{job}/{out.name}', size=out.stat().st_size)
    except Exception as exc:
        update(status='error', error=str(exc))


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def parse_request(self):
        if not super().parse_request():
            return False
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host') not in allowed:
            self.send_error(421, 'Use localhost or 127.0.0.1 to open this app.')
            return False
        return True

    def log_message(self, *args):
        pass

    def json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        try:
            if path == '/api/config':
                return self.json({'token':TOKEN, 'version':VERSION, 'ffmpeg':bool(shutil.which('ffmpeg'))})
            if path == '/api/sessions':
                result = []
                with LOCK:
                    for p in DATA.glob('*/session.json'):
                        data = json.loads(p.read_text())
                        result.append({k:v for k,v in data.items() if k != 'frames'} | {'count':len(data['frames'])})
                return self.json(sorted(result, key=lambda s:s['created'], reverse=True))
            if path.startswith('/api/sessions/'):
                key = path.rsplit('/',1)[-1]
                with LOCK:
                    data = session(key)
                return self.json(data)
            if path.startswith('/api/jobs/'):
                with LOCK:
                    job = JOBS.get(path.rsplit('/',1)[-1],{}).copy()
                return self.json(job or {'error':'No se encontró la exportación.'},200 if job else 404)
            if path.startswith('/backup/'):
                key = path.rsplit('/',1)[-1]
                if key == 'demo':
                    raise ValueError('La demo ya está incluida en el proyecto.')
                with LOCK:
                    data = session(key)
                    manifest = json.dumps(data, ensure_ascii=False).encode()
                backup = DATA/'backups'/f'{key}.zip'
                backup.parent.mkdir(exist_ok=True)
                with zipfile.ZipFile(backup, 'w', compression=zipfile.ZIP_STORED) as z:
                    z.writestr('session.json', manifest)
                    for frame in data['frames']:
                        z.write(folder_for(key)/'frames'/frame['file'], 'frames/'+frame['file'])
                return self.file(backup, attachment='timelinelapse-session.zip')
            base, relative = ROOT/'web', path.lstrip('/') or 'index.html'
            if path.startswith('/assets/'):
                base, relative = ROOT/'assets',path[len('/assets/'):]
            elif path.startswith('/frames/'):
                parts = path.split('/')
                if len(parts) != 4:
                    raise ValueError('Captura inválida.')
                base, relative = folder_for(parts[2])/'frames', parts[3]
            elif path.startswith('/exports/'):
                base, relative = DATA/'exports', path[len('/exports/'):]
                if Path(relative).name != 'timelinelapse.mp4':
                    raise ValueError('Archivo no disponible.')
            target = (base/relative).resolve()
            if not target.is_relative_to(base.resolve()) or not target.is_file():
                return self.json({'error':'Archivo no encontrado.'},404)
            return self.file(target, attachment='timelinelapse.mp4' if path.startswith('/exports/') else None)
        except (ValueError,OSError,json.JSONDecodeError) as exc:
            self.json({'error':str(exc)},400)

    def file(self, path, attachment=None):
        size = path.stat().st_size
        start,end = 0,size-1
        range_header = self.headers.get('Range','')
        if range_header:
            try:
                if not range_header.startswith('bytes=') or ',' in range_header:
                    raise ValueError
                left,right = range_header[6:].split('-',1)
                if left:
                    start = int(left)
                    end = min(size-1,int(right)) if right else size-1
                else:
                    start = max(0,size-int(right))
                if start < 0 or start >= size or end < start:
                    raise ValueError
            except ValueError:
                self.send_response(416)
                self.send_header('Content-Range',f'bytes */{size}')
                self.send_header('Content-Length','0')
                self.end_headers()
                return
        self.send_response(206 if range_header else 200)
        self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length',str(end-start+1))
        self.send_header('Accept-Ranges','bytes')
        self.send_header('X-Content-Type-Options','nosniff')
        if range_header:
            self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        if attachment:
            self.send_header('Content-Disposition',f'attachment; filename="{attachment}"')
        self.end_headers()
        try:
            with path.open('rb') as f:
                f.seek(start)
                remaining = end-start+1
                while remaining:
                    chunk = f.read(min(1024*1024,remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        path = urlparse(self.path).path
        origin = self.headers.get('Origin')
        if self.headers.get('X-TimelineLapse-Token') != TOKEN or (origin and origin != f'http://{self.headers.get("Host")}'):
            self.close_connection = True
            return self.json({'error':'Sesión vencida. Recargá la página.'},403)
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 0 < size <= (12*1024*1024 if path.endswith('/frame') else 16384):
                self.close_connection = True
                return self.json({'error':'Solicitud demasiado grande o vacía.'},413)
            body = self.rfile.read(size)
            if len(body) != size:
                raise ValueError('Se interrumpió la carga.')
            if path == '/api/sessions':
                opts = json.loads(body)
                with LOCK:
                    data = new_session(opts.get('title'),opts.get('interval',3))
                return self.json(data,201)
            if path.startswith('/api/sessions/') and path.endswith('/frame'):
                key = path.split('/')[-2]
                count = add_frame(key,body,self.headers.get('X-Elapsed','0'))
                return self.json({'count':count})
            if path.startswith('/api/sessions/') and path.endswith('/finish'):
                key = path.split('/')[-2]
                if key == 'demo':
                    raise ValueError('La demo es de solo lectura.')
                opts = json.loads(body)
                with LOCK:
                    data = session(key)
                    data['elapsed'] = number(opts.get('elapsed'), data['elapsed'], 86400*365)
                    data['title'] = text(opts.get('title',data['title']),48) or 'Mi edición'
                    data['closed'] = True
                    data['skipped'] = int(number(opts.get('skipped',data.get('skipped',0)),0,1e9))
                    save_session(data)
                return self.json(data)
            if path == '/api/render':
                opts = json.loads(body)
                with LOCK:
                    data = session(opts.get('session',''))
                    if len(data['frames']) < 2:
                        raise ValueError('Guardá al menos dos capturas antes de exportar.')
                    key = secrets.token_hex(12)
                    JOBS[key] = {'status':'queued','progress':0}
                POOL.submit(render_job,key,data['id'],opts)
                return self.json({'id':key},202)
            return self.json({'error':'Ruta no encontrada.'},404)
        except (ValueError,KeyError,OSError,struct.error) as exc:
            self.json({'error':str(exc)},400)


def main():
    parser = argparse.ArgumentParser(description='Turn the making of your edit into a timelapse.')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    args = parser.parse_args()
    DATA.mkdir(exist_ok=True)
    try:
        server = ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    except OSError as exc:
        parser.exit(1,f'Could not open port {args.port}: {exc}. Try --port 8766\n')
    url = f'http://127.0.0.1:{args.port}'
    print(f'TimelineLapse {VERSION} · {url}\nFrames stay on this computer. Ctrl+C to stop.',flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nSession saved. See you at the next cut.')
    finally:
        server.server_close()
        POOL.shutdown(wait=True,cancel_futures=True)


if __name__ == '__main__':
    main()
