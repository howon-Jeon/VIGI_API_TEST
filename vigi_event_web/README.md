# VIGI 이벤트 수신 테스트 웹

Python 표준 라이브러리만 사용하는 VIGI NVR 이벤트 서버 테스트 앱입니다.

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

처음에는 NVR이 실제로 어떤 multipart 필드명으로 JPEG를 보내는지 확인하는 목적이 큽니다.
이미지가 표시되지 않더라도 raw 파일과 DB의 raw_payload를 보면 다음 단계에서 정확히 맞출 수 있습니다.
