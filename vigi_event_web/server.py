from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import base64
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from urllib.parse import quote


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads" / "events"
RAW_DIR = BASE_DIR / "uploads" / "raw"
DB_PATH = DATA_DIR / "events.sqlite3"
CONFIG_PATH = BASE_DIR / "config.json"
HOST = "0.0.0.0"
PORT = 8080
DEFAULT_CAMERA_IP = "192.168.10.162"
DEFAULT_SNAPSHOT_DELAY_SECONDS = 3


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    ensure_dirs()
    with db() as conn:
        conn.execute(
            """
            create table if not exists events (
                id integer primary key autoincrement,
                event_time text,
                camera_channel text,
                event_type text,
                image_path text,
                raw_path text,
                raw_payload text,
                content_type text,
                remote_addr text,
                created_at text not null
            )
            """
        )


def load_config():
    config = {
        "camera_ip": DEFAULT_CAMERA_IP,
        "snapshot_delay_seconds": DEFAULT_SNAPSHOT_DELAY_SECONDS,
        "rtsp_urls": [
            "rtsp://{username}:{password}@{ip}:554/stream1",
            "rtsp://{username}:{password}@{ip}:554/stream2",
        ],
        "ffmpeg_path": os.environ.get("FFMPEG_PATH", "ffmpeg"),
        "camera_username": os.environ.get("VIGI_CAMERA_USERNAME", "admin"),
        "camera_password": os.environ.get("VIGI_CAMERA_PASSWORD", ""),
    }
    if CONFIG_PATH.exists():
        try:
            file_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(file_config, dict):
                config.update({key: value for key, value in file_config.items() if value is not None})
        except json.JSONDecodeError:
            print(f"Invalid JSON config: {CONFIG_PATH}")
    return config


def now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def safe_filename(name):
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "")
    return cleaned.strip("._") or "capture.jpg"


def parse_header_value(value):
    parts = [part.strip() for part in (value or "").split(";")]
    main = parts[0].lower() if parts else ""
    params = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        raw = raw.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            raw = raw[1:-1]
        params[key.strip().lower()] = raw
    return main, params


def guess_event_fields(payload):
    if not isinstance(payload, dict):
        return "", "human"

    vigi_event = payload.get("event")
    if isinstance(vigi_event, dict):
        event_types = []
        for item in vigi_event.get("event_list", []):
            if isinstance(item, dict):
                raw_types = item.get("event_type", [])
                if isinstance(raw_types, list):
                    event_types.extend(str(value) for value in raw_types)
                elif raw_types:
                    event_types.append(str(raw_types))
        channel = str(vigi_event.get("ip") or vigi_event.get("device_name") or "")
        return channel, "+".join(event_types) or "human"

    channel_keys = ("channel", "chn", "chn_id", "channel_id", "camera", "camera_id", "device_id")
    type_keys = ("event_type", "event", "type", "eventName", "event_name", "alarm_type")

    channel = next((str(payload[k]) for k in channel_keys if k in payload and payload[k] is not None), "")
    event_type = next((str(payload[k]) for k in type_keys if k in payload and payload[k] is not None), "")
    return channel, event_type or "human"


def filter_event_type(event_type):
    parts = [
        part.strip().upper()
        for part in re.split(r"[+,/ ]+", event_type or "")
        if part.strip()
    ]
    allowed = [part for part in parts if part in ("PEOPLE", "HUMAN")]
    return "+".join(dict.fromkeys(allowed))


def insert_event(event_time, camera_channel, event_type, image_path, raw_path, raw_payload, content_type, remote_addr):
    with db() as conn:
        cur = conn.execute(
            """
            insert into events (
                event_time, camera_channel, event_type, image_path, raw_path,
                raw_payload, content_type, remote_addr, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_time,
                camera_channel,
                event_type,
                image_path,
                raw_path,
                raw_payload,
                content_type,
                remote_addr,
                now_text(),
            ),
        )
        return cur.lastrowid


def row_to_dict(row):
    item = dict(row)
    if item.get("image_path"):
        item["image_url"] = "/" + item["image_path"].replace("\\", "/")
    else:
        item["image_url"] = ""
    item["snapshot_status"] = {}
    if item.get("raw_payload"):
        try:
            payload = json.loads(item["raw_payload"])
            snapshot_status = payload.get("_snapshot_status")
            if isinstance(snapshot_status, dict):
                item["snapshot_status"] = snapshot_status
        except json.JSONDecodeError:
            pass
    return item


def read_events(limit=30):
    with db() as conn:
        rows = conn.execute(
            "select * from events order by id desc limit ?",
            (limit,),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def latest_event():
    with db() as conn:
        row = conn.execute("select * from events order by id desc limit 1").fetchone()
    return row_to_dict(row) if row else None


def update_event_snapshot(event_id, image_path, status, error=""):
    with db() as conn:
        row = conn.execute(
            "select image_path, raw_payload from events where id = ?",
            (event_id,),
        ).fetchone()
        if not row:
            return False

        previous_image_path = row["image_path"]
        try:
            payload = json.loads(row["raw_payload"] or "{}")
        except json.JSONDecodeError:
            payload = {"raw_payload": row["raw_payload"] or ""}

        payload["_snapshot_status"] = {
            "status": status,
            "delay_seconds": load_config().get("snapshot_delay_seconds", DEFAULT_SNAPSHOT_DELAY_SECONDS),
            "updated_at": now_text(),
        }
        if error:
            payload["_snapshot_status"]["error"] = str(error)

        conn.execute(
            "update events set image_path = ?, raw_payload = ? where id = ?",
            (image_path, json.dumps(payload, ensure_ascii=False, indent=2), event_id),
        )

    if previous_image_path and previous_image_path != image_path:
        remove_relative_file(previous_image_path)
    return True


def update_event_snapshot_status(event_id, status, error=""):
    with db() as conn:
        row = conn.execute("select raw_payload from events where id = ?", (event_id,)).fetchone()
        if not row:
            return False

        try:
            payload = json.loads(row["raw_payload"] or "{}")
        except json.JSONDecodeError:
            payload = {"raw_payload": row["raw_payload"] or ""}

        snapshot_status = payload.get("_snapshot_status")
        if not isinstance(snapshot_status, dict):
            snapshot_status = {}
        snapshot_status.update({"status": status, "updated_at": now_text()})
        if error:
            snapshot_status["error"] = str(error)
        payload["_snapshot_status"] = snapshot_status

        conn.execute(
            "update events set raw_payload = ? where id = ?",
            (json.dumps(payload, ensure_ascii=False, indent=2), event_id),
        )
    return True


def remove_relative_file(relative_path):
    if not relative_path:
        return
    path = (BASE_DIR / relative_path).resolve()
    if not str(path).startswith(str(BASE_DIR.resolve())):
        return
    if path.exists() and path.is_file():
        path.unlink()


def delete_event(event_id):
    with db() as conn:
        row = conn.execute(
            "select image_path, raw_path from events where id = ?",
            (event_id,),
        ).fetchone()
        if not row:
            return False
        conn.execute("delete from events where id = ?", (event_id,))

    remove_relative_file(row["image_path"])
    remove_relative_file(row["raw_path"])
    return True


def clear_events():
    with db() as conn:
        rows = conn.execute("select image_path, raw_path from events").fetchall()
        conn.execute("delete from events")

    for row in rows:
        remove_relative_file(row["image_path"])
        remove_relative_file(row["raw_path"])
    return len(rows)


def rtsp_urls(camera_ip):
    config = load_config()
    configured = config.get("rtsp_urls", [])
    if isinstance(configured, str):
        configured = [configured]

    username = quote(str(config.get("camera_username") or ""), safe="")
    password = quote(str(config.get("camera_password") or ""), safe="")
    urls = []
    for template in configured:
        url = str(template).strip()
        if url:
            urls.append(url.format(ip=camera_ip, username=username, password=password))
    return urls


def redact_url(value):
    return re.sub(r"(rtsp://[^:/@]+:)[^@]+@", r"\1***@", str(value))


def camera_ip_from_payload(payload, fallback_ip):
    if isinstance(payload, dict):
        event = payload.get("event")
        if isinstance(event, dict) and event.get("ip"):
            return str(event["ip"])
        for key in ("ip", "camera_ip", "device_ip", "host"):
            if payload.get(key):
                return str(payload[key])
    config_ip = str(load_config().get("camera_ip") or "").strip()
    return config_ip or fallback_ip


def find_ffmpeg():
    config = load_config()
    configured = str(config.get("ffmpeg_path") or "ffmpeg").strip()
    if Path(configured).exists():
        return configured
    found = shutil.which(configured)
    if found:
        return found
    return ""


def capture_rtsp_frame(url, output_path):
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed or ffmpeg_path is not configured.")

    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-i",
        url,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-y",
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "ffmpeg failed").strip())
    data = output_path.read_bytes()
    if not data.startswith(b"\xff\xd8"):
        raise RuntimeError("ffmpeg output is not JPEG.")
    return data


def save_rtsp_snapshot(event_id, camera_ip):
    errors = []
    for url in rtsp_urls(camera_ip):
        filename = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_rtsp.jpg"
        path = UPLOAD_DIR / filename
        try:
            capture_rtsp_frame(url, path)
            image_path = str(path.relative_to(BASE_DIR))
            if not update_event_snapshot(event_id, image_path, "saved_rtsp"):
                remove_relative_file(image_path)
            print(f"RTSP frame capture saved for event {event_id}: {redact_url(url)}")
            return True, ""
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            remove_relative_file(str(path.relative_to(BASE_DIR)))
            errors.append(f"{redact_url(url)} - {error}")
    return False, " | ".join(errors) if errors else "RTSP capture failed."


def save_delayed_snapshot(event_id, payload, remote_addr):
    config = load_config()
    delay_seconds = float(config.get("snapshot_delay_seconds") or DEFAULT_SNAPSHOT_DELAY_SECONDS)
    time.sleep(delay_seconds)

    camera_ip = camera_ip_from_payload(payload, remote_addr)
    update_event_snapshot_status(event_id, "capturing_rtsp")
    rtsp_ok, rtsp_error = save_rtsp_snapshot(event_id, camera_ip)
    if rtsp_ok:
        return

    update_event_snapshot_status(event_id, "failed", rtsp_error)
    print(f"Delayed RTSP capture failed for event {event_id}: {rtsp_error}")


def schedule_delayed_snapshot(event_id, payload, remote_addr):
    thread = threading.Thread(
        target=save_delayed_snapshot,
        args=(event_id, payload, remote_addr),
        daemon=True,
    )
    thread.start()


def parse_multipart(body, content_type):
    _, params = parse_header_value(content_type)
    boundary = params.get("boundary")
    if not boundary:
        return {}, []

    boundary_bytes = ("--" + boundary).encode()
    fields = {}
    files = []

    for part in body.split(boundary_bytes):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2].strip(b"\r\n")
        if b"\r\n\r\n" not in part:
            continue

        header_blob, data = part.split(b"\r\n\r\n", 1)
        headers = {}
        for line in header_blob.decode("utf-8", errors="replace").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()

        disposition = headers.get("content-disposition", "")
        _, disp_params = parse_header_value(disposition)
        name = disp_params.get("name", "")
        filename = disp_params.get("filename")
        part_type = headers.get("content-type", "")

        is_image_data = part_type.lower().startswith("image/") or data.startswith(b"\xff\xd8")

        if filename or is_image_data:
            files.append(
                {
                    "field": name,
                    "filename": filename or f"{name or 'capture'}.jpg",
                    "content_type": part_type or ("image/jpeg" if data.startswith(b"\xff\xd8") else ""),
                    "data": data,
                }
            )
        elif name:
            fields[name] = data.decode("utf-8", errors="replace")

    return fields, files


def parse_payload(body, content_type):
    content_type_lower = (content_type or "").lower()
    payload = {}
    image_path = ""

    if "multipart/form-data" in content_type_lower:
        fields, files = parse_multipart(body, content_type)
        payload = dict(fields)
        for key, value in list(fields.items()):
            value = value.strip()
            if value.startswith("{") or value.startswith("["):
                try:
                    payload[key] = json.loads(value)
                    if isinstance(payload[key], dict):
                        payload.update(payload[key])
                except json.JSONDecodeError:
                    pass

        image_file = next(
            (
                item
                for item in files
                if item["content_type"].lower().startswith("image/")
                or item["data"].startswith(b"\xff\xd8")
            ),
            None,
        )
        if image_file:
            ext = Path(safe_filename(image_file["filename"])).suffix
            if not ext:
                ext = ".jpg"
            filename = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
            path = UPLOAD_DIR / filename
            path.write_bytes(image_file["data"])
            image_path = str(path.relative_to(BASE_DIR))

        payload["_multipart_files"] = [
            {
                "field": item["field"],
                "filename": item["filename"],
                "content_type": item["content_type"],
                "size": len(item["data"]),
            }
            for item in files
        ]
        return payload, image_path

    if "application/json" in content_type_lower:
        try:
            payload = json.loads(body.decode("utf-8", errors="replace") or "{}")
        except json.JSONDecodeError:
            payload = {"raw_text": body.decode("utf-8", errors="replace")}
        return payload, image_path

    if "application/x-www-form-urlencoded" in content_type_lower:
        parsed = parse_qs(body.decode("utf-8", errors="replace"))
        payload = {key: values[-1] if values else "" for key, values in parsed.items()}
        return payload, image_path

    if body.startswith(b"\xff\xd8"):
        filename = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
        path = UPLOAD_DIR / filename
        path.write_bytes(body)
        image_path = str(path.relative_to(BASE_DIR))
        return {"raw_binary": "jpeg", "size": len(body)}, image_path

    return {"raw_text": body[:5000].decode("utf-8", errors="replace")}, image_path


INDEX_HTML = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VIGI Human Detection Monitor</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header class="topbar">
    <div>
      <p class="eyebrow">VIGI NVR Event Receiver</p>
      <h1>사람 감지 캡처 모니터</h1>
    </div>
    <div class="status">
      <span class="dot" id="statusDot"></span>
      <span id="statusText">대기 중</span>
    </div>
  </header>

  <main class="layout">
    <section class="viewer">
      <div class="viewer-head">
        <div>
          <h2>최신 감지 이미지</h2>
          <p id="latestMeta">아직 수신된 이벤트가 없습니다.</p>
        </div>
        <button id="refreshBtn" type="button">새로고침</button>
      </div>
      <div class="image-stage" id="imageStage">
        <div class="empty">NVR 이벤트가 들어오면 JPEG가 여기에 표시됩니다.</div>
      </div>
    </section>

    <aside class="side">
      <section class="panel">
        <h2>서버 등록값</h2>
        <dl>
          <dt>Protocol</dt><dd>HTTP</dd>
          <dt>Port</dt><dd>8080</dd>
          <dt>URL</dt><dd>/api/vigi/event</dd>
          <dt>Picture Switch</dt><dd>ON</dd>
        </dl>
      </section>

      <section class="panel">
        <h2>테스트 업로드</h2>
        <form id="testForm">
          <label>이벤트 JSON</label>
          <textarea name="event" rows="5">{"event_type":"human","channel":"1","source":"manual-test"}</textarea>
          <label>JPEG 이미지</label>
          <input name="picture" type="file" accept="image/jpeg,image/png">
          <button type="submit">POST 테스트</button>
        </form>
      </section>
    </aside>

    <section class="history">
      <div class="viewer-head">
        <div>
          <h2>최근 이벤트</h2>
          <p>5초마다 자동 갱신됩니다.</p>
        </div>
        <button id="clearEventsBtn" class="danger" type="button">전체 제거</button>
      </div>
      <div class="event-list" id="eventList"></div>
    </section>
  </main>

  <script src="/static/app.js"></script>
</body>
</html>
"""


STYLE_CSS = """
:root {
  color-scheme: light;
  font-family: "Segoe UI", "Malgun Gothic", Arial, sans-serif;
  background: #f4f6f8;
  color: #1c2530;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  min-height: 100vh;
  background: #f4f6f8;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 24px 32px;
  background: #17202a;
  color: #fff;
}

.eyebrow {
  margin: 0 0 6px;
  color: #82c7b8;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0;
}

h1, h2, p { margin-top: 0; }
h1 { margin-bottom: 0; font-size: 28px; letter-spacing: 0; }
h2 { margin-bottom: 6px; font-size: 18px; letter-spacing: 0; }
p { color: #647180; }

.status {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 9px 13px;
  border: 1px solid rgba(255,255,255,0.18);
  border-radius: 6px;
  background: rgba(255,255,255,0.08);
  white-space: nowrap;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: #a8b3bd;
}

.dot.live { background: #35d18b; box-shadow: 0 0 0 4px rgba(53,209,139,0.16); }

.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 18px;
  padding: 18px;
}

.viewer, .history, .panel {
  background: #fff;
  border: 1px solid #dfe5ea;
  border-radius: 8px;
}

.viewer, .history { min-width: 0; }

.viewer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border-bottom: 1px solid #e7edf2;
}

.viewer-head p { margin-bottom: 0; font-size: 14px; }

button {
  min-height: 38px;
  border: 0;
  border-radius: 6px;
  padding: 0 14px;
  background: #16776b;
  color: #fff;
  font-weight: 700;
  cursor: pointer;
}

button:hover { background: #126459; }

button.danger {
  background: #b33b3b;
}

button.danger:hover {
  background: #932f2f;
}

button.ghost-danger {
  min-height: 32px;
  padding: 0 10px;
  background: #fff;
  border: 1px solid #d7a7a7;
  color: #9a3030;
}

button.ghost-danger:hover {
  background: #fff1f1;
}

.image-stage {
  display: grid;
  place-items: center;
  min-height: 460px;
  background: #0f1419;
  overflow: hidden;
}

.image-stage img {
  width: 100%;
  height: 100%;
  max-height: 620px;
  object-fit: contain;
  display: block;
}

.empty {
  max-width: 360px;
  color: #cbd5df;
  text-align: center;
  line-height: 1.6;
  padding: 24px;
}

.side {
  display: grid;
  align-content: start;
  gap: 18px;
}

.panel { padding: 16px; }

dl {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 9px 12px;
  margin: 14px 0 0;
}

dt {
  color: #647180;
  font-size: 13px;
}

dd {
  margin: 0;
  font-weight: 700;
  overflow-wrap: anywhere;
}

form {
  display: grid;
  gap: 10px;
}

label {
  color: #405060;
  font-size: 13px;
  font-weight: 700;
}

textarea, input[type="file"] {
  width: 100%;
  border: 1px solid #ccd6dd;
  border-radius: 6px;
  padding: 10px;
  font: inherit;
}

.history {
  grid-column: 1 / -1;
}

.event-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
  padding: 16px;
}

.event-card {
  border: 1px solid #e0e7ec;
  border-radius: 8px;
  overflow: hidden;
  background: #fbfcfd;
}

.event-card img {
  width: 100%;
  aspect-ratio: 16 / 10;
  object-fit: cover;
  display: block;
  background: #111820;
}

.event-card .no-image {
  display: grid;
  place-items: center;
  aspect-ratio: 16 / 10;
  background: #edf1f4;
  color: #6b7886;
}

.event-body {
  padding: 11px 12px 12px;
}

.event-body strong {
  display: block;
  margin-bottom: 4px;
}

.event-body span {
  display: block;
  color: #687684;
  font-size: 13px;
  line-height: 1.45;
}

.event-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}

@media (max-width: 900px) {
  .topbar {
    align-items: flex-start;
    flex-direction: column;
    padding: 20px;
  }

  .layout {
    grid-template-columns: 1fr;
    padding: 12px;
  }

  .image-stage {
    min-height: 320px;
  }
}
"""


APP_JS = """
const latestMeta = document.getElementById("latestMeta");
const imageStage = document.getElementById("imageStage");
const eventList = document.getElementById("eventList");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const refreshBtn = document.getElementById("refreshBtn");
const clearEventsBtn = document.getElementById("clearEventsBtn");
const testForm = document.getElementById("testForm");

function cacheBust(url) {
  if (!url) return "";
  return `${url}?t=${Date.now()}`;
}

function setStatus(ok, text) {
  statusDot.classList.toggle("live", ok);
  statusText.textContent = text;
}

function eventTitle(item) {
  const type = item.event_type || "event";
  const channel = item.camera_channel ? `CH ${item.camera_channel}` : "채널 미확인";
  return `${channel} · ${type}`;
}

function snapshotMessage(item) {
  const status = item.snapshot_status || {};
  if (status.status === "failed") {
    return `3초 후 RTSP 캡처 실패: ${status.error || "RTSP 설정과 ffmpeg 설치를 확인하세요."}`;
  }
  if (status.status === "capturing_rtsp") {
    return "3초가 지나 RTSP 프레임을 캡처하는 중입니다.";
  }
  return "사람 감지 이벤트를 받았습니다. 3초 후 RTSP 프레임을 캡처합니다.";
}

function renderLatest(item) {
  if (!item) {
    latestMeta.textContent = "아직 수신된 이벤트가 없습니다.";
    imageStage.innerHTML = '<div class="empty">NVR 이벤트가 들어오면 JPEG가 여기에 표시됩니다.</div>';
    return;
  }

  latestMeta.textContent = `${eventTitle(item)} · ${item.created_at}`;
  if (item.image_url) {
    imageStage.innerHTML = `<img src="${cacheBust(item.image_url)}" alt="최신 사람 감지 캡처">`;
  } else {
    imageStage.innerHTML = `<div class="empty">${snapshotMessage(item)}</div>`;
  }
}

function renderEvents(items) {
  if (!items.length) {
    eventList.innerHTML = '<div class="empty">표시할 이벤트가 없습니다.</div>';
    return;
  }

  eventList.innerHTML = items.map((item) => {
    const image = item.image_url
      ? `<img src="${cacheBust(item.image_url)}" alt="감지 캡처">`
      : `<div class="no-image">${snapshotMessage(item)}</div>`;
    return `
      <article class="event-card">
        ${image}
        <div class="event-body">
          <strong>${eventTitle(item)}</strong>
          <span>${item.created_at}</span>
          <span>${item.remote_addr || ""}</span>
          <div class="event-actions">
            <button class="ghost-danger delete-event-btn" type="button" data-id="${item.id}">제거</button>
          </div>
        </div>
      </article>
    `;
  }).join("");
}

async function loadEvents() {
  try {
    const res = await fetch("/api/events?limit=24");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderLatest(data.events[0] || null);
    renderEvents(data.events || []);
    setStatus(true, "수신 대기 중");
  } catch (error) {
    setStatus(false, "서버 연결 오류");
    latestMeta.textContent = error.message;
  }
}

refreshBtn.addEventListener("click", loadEvents);

eventList.addEventListener("click", async (event) => {
  const button = event.target.closest(".delete-event-btn");
  if (!button) return;
  const id = button.dataset.id;
  if (!confirm("이 이벤트를 제거할까요?")) return;

  const res = await fetch(`/api/events/${id}`, { method: "DELETE" });
  if (!res.ok) {
    alert("이벤트 제거 실패");
    return;
  }
  await loadEvents();
});

clearEventsBtn.addEventListener("click", async () => {
  if (!confirm("최근 이벤트를 모두 제거할까요? 저장된 이미지와 원본 요청도 삭제됩니다.")) return;

  const res = await fetch("/api/events", { method: "DELETE" });
  if (!res.ok) {
    alert("전체 제거 실패");
    return;
  }
  await loadEvents();
});

testForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(testForm);
  const res = await fetch("/api/vigi/event", {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    alert("테스트 POST 실패");
    return;
  }
  await loadEvents();
});

loadEvents();
setInterval(loadEvents, 5000);
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s - %s" % (now_text(), self.client_address[0], fmt % args))

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, content_type="text/plain; charset=utf-8", status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path):
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        mime, _ = mimetypes.guess_type(str(path))
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self.send_text(INDEX_HTML, "text/html; charset=utf-8")
            return
        if path == "/static/style.css":
            self.send_text(STYLE_CSS, "text/css; charset=utf-8")
            return
        if path == "/static/app.js":
            self.send_text(APP_JS, "application/javascript; charset=utf-8")
            return
        if path == "/api/events/latest":
            self.send_json({"event": latest_event()})
            return
        if path == "/api/events":
            query = parse_qs(parsed.query)
            limit = min(max(int(query.get("limit", ["30"])[0]), 1), 100)
            self.send_json({"events": read_events(limit)})
            return
        if path.startswith("/uploads/events/"):
            filename = safe_filename(Path(path).name)
            self.send_file(UPLOAD_DIR / filename)
            return

        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/vigi/event":
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        content_type = self.headers.get("Content-Type", "")
        body = self.rfile.read(content_length)

        raw_name = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.bin"
        raw_path = RAW_DIR / raw_name
        raw_path.write_bytes(body)

        payload, image_path = parse_payload(body, content_type)
        camera_channel, raw_event_type = guess_event_fields(payload)
        event_type = filter_event_type(raw_event_type)
        if not event_type:
            remove_relative_file(image_path)
            remove_relative_file(str(raw_path.relative_to(BASE_DIR)))
            print(
                f"Ignored non-human event from {self.client_address[0]}: "
                f"raw_event_type={raw_event_type!r}"
            )
            self.send_json({"ok": True, "ignored": True, "reason": "not a human detection event"})
            return

        event_time = str(payload.get("event_time") or payload.get("time") or payload.get("timestamp") or now_text())
        if image_path:
            remove_relative_file(image_path)
            image_path = ""
        remove_relative_file(str(raw_path.relative_to(BASE_DIR)))
        raw_path_for_db = ""
        payload["_snapshot_status"] = {
            "status": "waiting",
            "delay_seconds": load_config().get("snapshot_delay_seconds", DEFAULT_SNAPSHOT_DELAY_SECONDS),
            "started_at": now_text(),
            "note": "NVR attached image and raw body were discarded. Waiting for RTSP frame capture.",
        }

        raw_payload = json.dumps(payload, ensure_ascii=False, indent=2)

        event_id = insert_event(
            event_time=event_time,
            camera_channel=camera_channel,
            event_type=event_type,
            image_path=image_path,
            raw_path=raw_path_for_db,
            raw_payload=raw_payload,
            content_type=content_type,
            remote_addr=self.client_address[0],
        )

        schedule_delayed_snapshot(event_id, payload, self.client_address[0])

        self.send_json(
            {
                "ok": True,
                "id": event_id,
                "image_saved": False,
                "rtsp_capture_scheduled": True,
                "image_path": image_path,
                "raw_saved": raw_path_for_db,
            }
        )

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/events":
            deleted_count = clear_events()
            self.send_json({"ok": True, "deleted": deleted_count})
            return

        match = re.fullmatch(r"/api/events/(\d+)", path)
        if match:
            event_id = int(match.group(1))
            if not delete_event(event_id):
                self.send_json({"ok": False, "error": "event not found"}, status=404)
                return
            self.send_json({"ok": True, "deleted": 1})
            return

        self.send_error(404)


if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"VIGI test receiver running at http://127.0.0.1:{PORT}")
    print(f"NVR URL: http://<this-pc-ip>:{PORT}/api/vigi/event")
    server.serve_forever()
