# VIGI API TEST

TP-Link VIGI 카메라에서 사람 감지 이벤트를 받아, 이벤트 발생 3초 뒤의 화면을 캡처해서 웹 화면에 표시하는 테스트 프로젝트입니다.

## 목표 흐름

```text
VIGI 카메라 사람 감지
→ 카메라가 우리 서버로 HTTP POST 이벤트 전송
→ 서버는 NVR/카메라가 첨부한 즉시 이미지를 사용하지 않음
→ 3초 대기
→ URL Snapshot API 시도
→ 실패하면 RTSP stream에서 현재 프레임 캡처
→ JPEG 저장
→ 웹에서 최신 이미지와 최근 이벤트 표시
```

## 프로젝트 구조

```text
vigi_event_web/
  server.py          Python 표준 라이브러리 기반 웹 서버
  run_server.bat     Windows 실행용 배치 파일
  README.md          간단 실행 안내
  config.json        로컬 카메라 접속 설정, Git 제외
  data/              SQLite DB, Git 제외
  uploads/events/    저장된 JPEG, Git 제외
  uploads/raw/       디버깅용 원본 요청, 현재 사람 감지 이벤트는 저장하지 않음
```

## 설치 요구사항

Python이 필요합니다.

```powershell
python --version
```

RTSP fallback 캡처를 사용하려면 `ffmpeg`가 필요합니다. Windows에서는 관리자 PowerShell에서 설치합니다.

```powershell
choco install ffmpeg -y
```

설치 확인:

```powershell
ffmpeg -version
```

`ffmpeg`가 PATH에 없으면 `vigi_event_web/config.json`의 `ffmpeg_path`에 `ffmpeg.exe` 전체 경로를 지정합니다.

```json
{
  "ffmpeg_path": "C:\\ffmpeg\\bin\\ffmpeg.exe"
}
```

## 서버 실행

```powershell
cd C:\Users\다원디엔에스\Documents\CCTV_TEST\vigi_event_web
python server.py
```

웹 화면:

```text
http://127.0.0.1:8080
```

LAN의 다른 장비에서 접속:

```text
http://서버PC_IP:8080
```

예:

```text
http://192.168.10.233:8080
```

## 서버 PC IP 확인

카메라가 이벤트를 보낼 대상은 카메라 IP가 아니라 서버 PC IP입니다.

```powershell
ipconfig
```

예:

```text
카메라 IP: 192.168.10.162
서버 PC IP: 192.168.10.233
```

## VIGI 알람 서버 설정

카메라 웹 설정에서 다음 메뉴로 이동합니다.

```text
Settings → Event → Alarm Server
```

알람 서버 값을 등록합니다.

```text
Host IP/Domain: 서버 PC IP
URL: /api/vigi/event
Protocol: HTTP
Port: 8080
Attach Image: on
```

예:

```text
Host IP/Domain: 192.168.10.233
URL: /api/vigi/event
Protocol: HTTP
Port: 8080
Attach Image: on
```

전체 URL:

```text
http://192.168.10.233:8080/api/vigi/event
```

`테스트` 버튼을 눌렀을 때 서버 터미널에 아래처럼 찍혀야 합니다.

```text
192.168.10.162 - "POST /api/vigi/event HTTP/1.1" 200 -
```

이 로그가 없으면 카메라가 서버에 도달하지 못한 것입니다. IP, 포트, 방화벽을 먼저 확인하세요.

## Windows 방화벽

카메라가 서버 PC의 8080 포트로 접근해야 합니다. 막혀 있으면 관리자 PowerShell에서 허용합니다.

```powershell
New-NetFirewallRule -DisplayName "VIGI Event Receiver 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow
```

관리자 권한이 아니면 `액세스가 거부되었습니다`가 뜹니다.

## 사람 감지 설정

카메라 웹 설정에서:

```text
Settings → Event → Smart Event → Human Detection
```

권장 설정:

```text
Human Detection: ON
Sensitivity: 70~80
Schedule: 필요한 시간대 전체 활성화
Record: 선택
Push Notification: 선택
Light/Sound Alarm: OFF 권장
```

이 서버는 이벤트 타입 중 `PEOPLE` 또는 `HUMAN`만 저장합니다.

```text
PEOPLE → 저장 및 3초 후 캡처
HUMAN → 저장 및 3초 후 캡처
MOTION 단독 → 무시
TAMPERING 단독 → 무시
MOTION+PEOPLE → PEOPLE로 처리
```

무시된 이벤트는 터미널에 아래처럼 표시됩니다.

```text
Ignored non-human event from 192.168.10.162: raw_event_type='MOTION'
```

## 로컬 설정 파일

`vigi_event_web/config.json`에 카메라 접속 정보를 저장합니다. 이 파일은 비밀번호가 들어가므로 `.gitignore`에 포함되어 있습니다.

예:

```json
{
  "camera_ip": "192.168.10.162",
  "snapshot_delay_seconds": 3,
  "snapshot_urls": [
    "https://{ip}:8443/snapshot",
    "http://{ip}:8800/snapshot"
  ],
  "rtsp_fallback_enabled": true,
  "rtsp_urls": [
    "rtsp://{username}:{password}@{ip}:554/stream1",
    "rtsp://{username}:{password}@{ip}:554/stream2"
  ],
  "ffmpeg_path": "ffmpeg",
  "camera_username": "admin",
  "camera_password": "카메라_비밀번호",
  "verify_ssl": false
}
```

`snapshot_delay_seconds` 값을 바꾸면 이벤트 후 캡처 대기 시간이 바뀝니다.

## URL Snapshot 방식

TP-Link 공식 FAQ 기준 VIGI IPC Snapshot URL 형식은 다음과 같습니다.

```text
https://IP:8443/snapshot
http://IP:8800/snapshot
```

서버는 Digest 인증으로 위 URL을 호출하고, 응답이 JPEG인지 확인합니다.

성공 조건:

```text
HTTP 응답 Content-Type: image/jpeg
또는 응답 바이트가 JPEG 헤더 FF D8로 시작
```

일부 카메라/펌웨어에서는 `/snapshot`이 로그인 HTML로 리다이렉트되거나 `400 Bad Request`를 반환할 수 있습니다. 이 경우 URL Snapshot은 실패하고 RTSP fallback으로 넘어갑니다.

## RTSP fallback 방식

URL Snapshot이 실패하면 서버는 RTSP stream에서 현재 프레임 1장을 JPEG로 캡처합니다.

TP-Link 공식 RTSP 형식:

```text
rtsp://IP/stream1
rtsp://IP/stream2
```

인증 포함 예:

```text
rtsp://admin:password@192.168.10.162:554/stream1
```

서버는 내부적으로 `ffmpeg`를 실행합니다.

```powershell
ffmpeg -hide_banner -loglevel error -rtsp_transport tcp -i rtsp://... -frames:v 1 -q:v 2 -y output.jpg
```

따라서 `ffmpeg`가 설치되어 있어야 합니다.

```powershell
choco install ffmpeg -y
```

## 제공 API

카메라 이벤트 수신:

```http
POST /api/vigi/event
```

최근 이벤트 목록:

```http
GET /api/events?limit=24
```

최신 이벤트 1개:

```http
GET /api/events/latest
```

전체 이벤트 삭제:

```http
DELETE /api/events
```

특정 이벤트 삭제:

```http
DELETE /api/events/{id}
```

저장된 이미지 접근:

```http
GET /uploads/events/파일명.jpg
```

## 구현 포인트

`POST /api/vigi/event` 처리 순서:

```text
1. multipart/form-data 또는 JSON 요청 수신
2. VIGI 이벤트 JSON 파싱
3. 이벤트 타입 추출
4. PEOPLE/HUMAN이 아니면 무시
5. NVR 첨부 이미지는 사용하지 않고 삭제
6. DB에 이벤트 상태 waiting 저장
7. 별도 thread에서 3초 대기
8. URL Snapshot 시도
9. URL Snapshot 실패 시 RTSP fallback 시도
10. JPEG 저장 후 DB image_path 갱신
11. 웹 UI가 5초 polling으로 최신 이미지 표시
```

웹 UI는 5초마다 목록을 갱신합니다.

```text
GET /api/events?limit=24
```

이 요청은 감지 이벤트가 아니라 화면 갱신 요청입니다.

## 로그 해석

정상 이벤트 수신:

```text
192.168.10.162 - "POST /api/vigi/event HTTP/1.1" 200 -
```

웹 화면 자동 갱신:

```text
127.0.0.1 - "GET /api/events?limit=24 HTTP/1.1" 200 -
```

URL Snapshot 실패 후 RTSP fallback 성공:

```text
Delayed URL snapshot failed ...
RTSP fallback snapshot saved for event ...
```

ffmpeg 미설치:

```text
ffmpeg is not installed or ffmpeg_path is not configured.
```

이 경우 `choco install ffmpeg -y` 후 서버를 재시작합니다.

## 문제 해결

### 알람 서버 테스트가 실패함

카메라 설정의 Host IP가 현재 서버 PC IP와 같은지 확인합니다.

```powershell
ipconfig
```

서버가 8080에서 대기 중인지 확인합니다.

```powershell
netstat -ano | Select-String ':8080'
```

정상 예:

```text
0.0.0.0:8080 LISTENING
```

### 이벤트는 들어오는데 이미지가 없음

URL Snapshot이 실패하고 RTSP fallback도 실패한 상태입니다.

확인:

```powershell
ffmpeg -version
```

설치:

```powershell
choco install ffmpeg -y
```

### 카메라 `/snapshot`이 로그인 화면으로 이동함

일부 VIGI 모델/펌웨어에서는 공식 URL Snapshot이 바로 JPEG를 반환하지 않을 수 있습니다.
이 프로젝트는 그 경우 RTSP fallback으로 프레임을 캡처하도록 구현되어 있습니다.

### 터미널에 POST가 안 찍힘

카메라 이벤트가 서버에 도달하지 않는 상태입니다.

확인 항목:

```text
알람 서버 Host IP가 서버 PC IP인지
Port가 8080인지
URL이 /api/vigi/event인지
Python 서버가 실행 중인지
Windows 방화벽에서 8080 inbound가 허용됐는지
```
