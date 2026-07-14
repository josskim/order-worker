# order-worker

인트라넷 주문서를 로컬 PC에서 자동으로 수집하고 인트라넷 API로 업로드하는 Python 워커입니다.

## 주요 기능

- 공급사 사이트별 로그인 및 주문서 엑셀 다운로드
- 인트라넷 주문서 등록 API 업로드
- 사이트별 성공/실패 로그 저장
- 텔레그램 실행 결과 알림
- Windows 작업 스케줄러를 통한 평일 자동 실행

## 지원 사이트

- 오너클랜
- 온채널 / F온채널
- 도매꾹 / F도매꾹
- 도매의신
- 스페셜오퍼

## 설치

```powershell
cd E:\dev\order-worker
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m playwright install chromium
```

## 환경 변수

`.env.example`을 참고해서 `.env`를 생성합니다.

```env
INTRANET_API_URL=http://localhost:3001/api/order-import
INTRANET_LOG_API_URL=http://localhost:3001/api/order-import/log
ORDER_WORKER_DOWNLOAD_DIR=E:\dev\order-worker\downloads
ORDER_WORKER_ARCHIVE_DIR=E:\dev\order-worker\archive
ORDER_WORKER_LOG_DIR=E:\dev\order-worker\logs
ORDER_WORKER_HEADLESS=1
DOMEGGOOK_WAIT_SECONDS=120
DOMEGGOOK_POLL_SECONDS=5
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

실제 `.env`에는 사이트 계정, DB URL, 텔레그램 토큰 등이 들어갈 수 있으므로 GitHub에 올리지 않습니다.

## 실행

사이트 목록 확인:

```powershell
.\.venv\Scripts\python.exe -m order_worker.main sites
```

전체 사이트 실행:

```powershell
.\.venv\Scripts\python.exe -m order_worker.main run --all
```

특정 사이트만 실행:

```powershell
.\.venv\Scripts\python.exe -m order_worker.main run --site onchannel
.\.venv\Scripts\python.exe -m order_worker.main run --site ownerclan
```

## 작업 스케줄러

평일 월요일부터 금요일까지 `08:30`부터 `15:00`까지 30분 간격으로 전체 사이트를 실행합니다.

송장 업로드 자동 작업은 아래 명령으로 등록합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-invoice-task.ps1
```

`Order Worker Weekday Invoice Upload` 작업이 월~금 오후 4시에 한 번 실행되며,
`real` 업로드 후 `fake` 업로드를 순차 실행합니다. 같은 날짜에 예약 스크립트가
다시 호출되더라도 일일 실행 표식으로 중복 업로드를 시작하지 않습니다.

등록:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "E:\dev\order-worker\scripts\install-task.ps1"
```

등록된 작업명:

```text
Order Worker Weekday Import
```

## 로그와 파일 보관

- 실행 로그: `logs/`
- 다운로드 임시 파일: `downloads/`
- 업로드 전 보관 파일: `archive/`

위 폴더들은 GitHub에 올리지 않습니다.

## 참고

도매꾹/F도매꾹은 엑셀 생성 후 다운로드 버튼이 늦게 생길 수 있습니다. 기본값은 최대 120초까지 5초 간격으로 확인하도록 설정되어 있습니다.
