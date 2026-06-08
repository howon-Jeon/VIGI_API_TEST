# VIGI 이벤트 수신 테스트 웹

Python 표준 라이브러리만 사용하는 VIGI NVR 이벤트 서버 테스트 앱입니다.
전체 구현 가이드와 다른 프로젝트 이식 설명은 상위 `README.md`를 참고하세요.

## 실행

```powershell
cd C:\Users\다원디엔에스\Documents\CCTV_TEST\vigi_event_web
python server.py
```

브라우저에서 열기:

```text
http://127.0.0.1:8080
```

## NVR Alarm/Event Server 설정 예시

```text
Protocol: HTTP
IP/Domain: 서버 PC의 LAN IP
Port: 8080
URL: /api/vigi/event
Picture Switch: ON
```

예시:

```text
http://192.168.0.50:8080/api/vigi/event
```

## 저장 위치

```text
vigi_event_web/uploads/events  JPEG 저장
vigi_event_web/uploads/raw     NVR 원본 POST body 저장
vigi_event_web/data/events.sqlite3  이벤트 DB
```

## 사람 감지 후 3초 뒤 URL Snapshot

이 앱은 사람 감지 이벤트가 들어와도 NVR이 첨부한 이미지는 사용하지 않습니다.
대신 이벤트 수신 3초 후 카메라 URL Snapshot API를 호출해 JPEG를 저장합니다.

TP-Link 공식 FAQ 기준 IPC Snapshot URL 형식:

```text
https://IP:8443/snapshot
http://IP:8800/snapshot
```

카메라 계정 정보와 URL 후보는 `config.json`에 저장합니다.
이 파일은 비밀번호가 들어가므로 Git에 커밋하지 않습니다.

URL Snapshot이 JPEG를 반환하지 않으면 RTSP fallback을 사용할 수 있습니다.
RTSP fallback은 `ffmpeg`가 설치되어 있거나 `config.json`의 `ffmpeg_path`에 실행 파일 경로가 지정되어 있어야 합니다.

Windows 설치 예:

```powershell
choco install ffmpeg -y
```

TP-Link 공식 FAQ 기준 VIGI RTSP URL 형식:

```text
rtsp://IP/stream1
rtsp://IP/stream2
```

처음에는 NVR이 실제로 어떤 multipart 필드명으로 JPEG를 보내는지 확인하는 목적이 큽니다.
이미지가 표시되지 않더라도 raw 파일과 DB의 raw_payload를 보면 다음 단계에서 정확히 맞출 수 있습니다.
