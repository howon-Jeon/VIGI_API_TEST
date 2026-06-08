# VIGI 이벤트 수신 테스트 웹

Python 표준 라이브러리만 사용하는 VIGI 이벤트 수신 웹앱입니다.
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

## 카메라 Alarm Server 설정

```text
Protocol: HTTP
IP/Domain: 서버 PC의 LAN IP
Port: 8080
URL: /api/vigi/event
Attach Image: ON
```

예:

```text
http://192.168.10.233:8080/api/vigi/event
```

## 사람 감지 후 3초 뒤 RTSP 캡처

이 앱은 사람 감지 이벤트가 들어와도 카메라가 첨부한 즉시 이미지는 사용하지 않습니다.
대신 이벤트 수신 3초 후 RTSP stream에서 현재 프레임 1장을 JPEG로 저장합니다.

RTSP 캡처에는 `ffmpeg`가 필요합니다.

```powershell
choco install ffmpeg -y
```

설치 확인:

```powershell
ffmpeg -version
```

## 저장 위치

```text
vigi_event_web/uploads/events       JPEG 저장
vigi_event_web/data/events.sqlite3  이벤트 DB
```

`config.json`, DB, 저장 이미지는 Git에 커밋하지 않습니다.
