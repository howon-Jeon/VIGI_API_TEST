# VIGI API TEST

TP-Link VIGI 카메라에서 사람 감지 이벤트를 받아, 이벤트 발생 3초 뒤 RTSP 영상 프레임을 JPEG로 캡처해 웹에 표시하는 테스트 프로젝트입니다.

## 핵심 흐름

```text
VIGI 카메라 사람 감지
→ 카메라가 우리 서버로 HTTP POST 이벤트 전송
→ 서버는 카메라가 이벤트와 함께 보낸 즉시 이미지를 사용하지 않음
→ 3초 대기
→ RTSP stream1/stream2에 접속
→ 현재 영상 프레임 1장을 JPEG로 캡처
→ 웹에서 최신 이미지와 최근 이벤트 표시
```

## 왜 RTSP 프레임 캡처인가?

VIGI의 `/snapshot` URL은 모델/펌웨어/설정에 따라 JPEG를 바로 반환하지 않을 수 있습니다. 테스트 중에는 `/snapshot`이 로그인 HTML, `400 Bad Request`, SSL 오류를 반환했습니다.

RTSP는 카메라가 계속 송출하는 실시간 영상 스트림입니다. 따라서 `/snapshot` API가 막혀 있어도 RTSP 스트림만 열려 있으면 현재 화면의 프레임을 뽑아 JPEG로 저장할 수 있습니다.

```text
/snapshot 방식: 카메라에게 사진 한 장을 요청
RTSP 캡처 방식: 실시간 영상에 접속해서 현재 프레임을 저장
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

Python:

```powershell
python --version
```

RTSP 프레임 캡처용 `ffmpeg`:

```powershell
ffmpeg -version
```

Windows에서 Chocolatey로 설치:

```powershell
choco install ffmpeg -y
```

관리자 PowerShell에서 실행하는 것을 권장합니다.

## ffmpeg는 반드시 설치해야 하나?

RTSP 프레임 캡처를 하려면 실행 환경에 `ffmpeg` 실행 파일이 필요합니다. 다만 반드시 “시스템에 설치”해야 하는 것은 아닙니다.

가능한 배포 방식은 세 가지입니다.

```text
1. 사용자 PC에 ffmpeg 설치
2. 앱과 ffmpeg.exe를 함께 번들
3. 서버 또는 백엔드 장비에만 ffmpeg 설치하고 앱은 API만 호출
```

### 1. 시스템 설치 방식

가장 단순합니다.

```powershell
choco install ffmpeg -y
```

장점:

```text
설정이 간단함
ffmpeg_path를 "ffmpeg"로 두면 됨
```

단점:

```text
사용자 PC마다 설치 필요
관리자 권한이 필요할 수 있음
```

### 2. 앱에 ffmpeg 번들

배포 앱 폴더 안에 `ffmpeg.exe`를 포함합니다.

예:

```text
my-app/
  backend/
  bin/
    ffmpeg.exe
```

`config.json`에서 경로 지정:

```json
{
  "ffmpeg_path": "C:\\path\\to\\my-app\\bin\\ffmpeg.exe"
}
```

웹뷰 기반 데스크톱 앱이라면 이 방식이 좋습니다. Electron, Tauri, PyInstaller 같은 패키징 환경에서 ffmpeg 바이너리를 같이 넣고, 백엔드가 그 경로를 사용하게 하면 됩니다.

주의:

```text
ffmpeg 라이선스 확인 필요
OS별 바이너리 필요
Windows/macOS/Linux 경로 처리 필요
```

### 3. 서버 캡처 방식

웹뷰 앱은 단순 UI만 담당하고, 실제 이벤트 수신과 RTSP 캡처는 별도 서버/미니 PC/NVR 옆 PC에서 처리합니다.

장점:

```text
사용자 앱마다 ffmpeg 설치 불필요
카메라와 같은 LAN에 있는 서버에서 안정적으로 캡처
권한/방화벽 관리가 쉬움
```

다른 곳에 배포할 제품 형태라면 이 방식이 가장 안정적입니다.

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

```powershell
ipconfig
```

예:

```text
카메라 IP: 192.168.10.162
서버 PC IP: 192.168.10.233
```

카메라 알람 서버에는 카메라 IP가 아니라 서버 PC IP를 넣어야 합니다.

## VIGI 알람 서버 설정

카메라 웹 설정:

```text
Settings → Event → Alarm Server
```

값:

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

테스트 성공 시 서버 터미널:

```text
192.168.10.162 - "POST /api/vigi/event HTTP/1.1" 200 -
```

## Windows 방화벽

카메라가 서버 PC의 8080 포트로 접근해야 합니다.

관리자 PowerShell:

```powershell
New-NetFirewallRule -DisplayName "VIGI Event Receiver 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow
```

## 사람 감지 설정

```text
Settings → Event → Smart Event → Human Detection
```

권장:

```text
Human Detection: ON
Sensitivity: 70~80
Schedule: 필요한 시간대 전체 활성화
Record: 선택
Push Notification: 선택
Light/Sound Alarm: OFF 권장
```

서버는 이벤트 타입 중 `PEOPLE` 또는 `HUMAN`만 저장합니다.

```text
PEOPLE → 저장 및 3초 후 RTSP 캡처
HUMAN → 저장 및 3초 후 RTSP 캡처
MOTION 단독 → 무시
TAMPERING 단독 → 무시
MOTION+PEOPLE → PEOPLE로 처리
```

## 로컬 설정 파일

`vigi_event_web/config.json`은 비밀번호가 들어가므로 Git에 커밋하지 않습니다.

예:

```json
{
  "camera_ip": "192.168.10.162",
  "snapshot_delay_seconds": 3,
  "rtsp_urls": [
    "rtsp://{username}:{password}@{ip}:554/stream1",
    "rtsp://{username}:{password}@{ip}:554/stream2"
  ],
  "ffmpeg_path": "ffmpeg",
  "camera_username": "admin",
  "camera_password": "카메라_비밀번호"
}
```

`snapshot_delay_seconds`는 이름은 남아 있지만 의미는 “이벤트 후 RTSP 캡처 대기 시간”입니다.

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

저장 이미지 접근:

```http
GET /uploads/events/파일명.jpg
```

## 구현 순서

```text
1. POST /api/vigi/event 수신
2. VIGI 이벤트 JSON 파싱
3. PEOPLE/HUMAN 필터링
4. NVR 첨부 이미지와 raw body 삭제
5. DB에 waiting 상태 저장
6. 별도 thread에서 3초 대기
7. ffmpeg로 RTSP stream1 캡처 시도
8. 실패하면 stream2 캡처 시도
9. JPEG 저장 후 DB image_path 갱신
10. 웹 UI가 5초 polling으로 최신 이미지 표시
```

## 로그 해석

정상 이벤트 수신:

```text
192.168.10.162 - "POST /api/vigi/event HTTP/1.1" 200 -
```

웹 화면 자동 갱신:

```text
127.0.0.1 - "GET /api/events?limit=24 HTTP/1.1" 200 -
```

RTSP 캡처 성공:

```text
RTSP frame capture saved for event 51: rtsp://admin:***@192.168.10.162:554/stream1
```

ffmpeg 미설치:

```text
ffmpeg is not installed or ffmpeg_path is not configured.
```

## 문제 해결

### 알람 서버 테스트가 실패함

확인:

```powershell
ipconfig
netstat -ano | Select-String ':8080'
```

정상:

```text
0.0.0.0:8080 LISTENING
```

### 이벤트는 들어오는데 이미지가 없음

대부분 ffmpeg 문제입니다.

```powershell
ffmpeg -version
```

설치:

```powershell
choco install ffmpeg -y
```

### RTSP 인증 실패

확인:

```text
카메라 계정/비밀번호
RTSP 포트 554
ONVIF 또는 RTSP 서비스 활성화
특수문자 비밀번호 URL 인코딩
```

코드는 비밀번호를 자동 URL 인코딩합니다.

### 웹뷰 앱에서 구현할 때

권장 구조:

```text
웹뷰 UI
→ 로컬 백엔드 API 호출
→ 백엔드가 이벤트 수신/RTSP 캡처
→ ffmpeg는 앱 번들 또는 서버에 포함
```

웹뷰 자체에서 RTSP를 직접 캡처하는 것보다, 백엔드에서 ffmpeg를 실행해 JPEG를 만들고 웹뷰는 이미지를 표시하는 구조가 안정적입니다.
