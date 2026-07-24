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
INTRANET_RUN_HISTORY_API_URL=http://localhost:3001/api/order-worker/run-history
ORDER_WORKER_RUN_HISTORY_TOKEN=
ORDER_WORKER_DOWNLOAD_DIR=E:\dev\order-worker\downloads
ORDER_WORKER_ARCHIVE_DIR=E:\dev\order-worker\archive
ORDER_WORKER_LOG_DIR=E:\dev\order-worker\logs
ORDER_WORKER_HEADLESS=1
DOMEGGOOK_ACTION_WAIT_SECONDS=90
DOMEGGOOK_WAIT_SECONDS=600
DOMEGGOOK_POLL_SECONDS=3
DOMEGGOOK_DOWNLOAD_TIMEOUT_SECONDS=90
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
인트라넷 DB에 해당 날짜 실행을 먼저 등록한 후 `real` 업로드와 `fake` 업로드를
순차 실행합니다. 같은 날짜에 작업이 다시 호출되더라도 두 번째 실행은 업로드를
시작하지 않습니다.

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

도매꾹/F도매꾹은 엑셀 요청 화면과 iframe/팝업을 최대 90초까지 확인합니다. 파일 생성요청 후에는 `다운받기` 버튼이 실제로 보이고 활성화될 때까지 최대 600초 동안 3초 간격으로 새로고침하며 확인하고, 다운로드 이벤트도 최대 90초까지 기다립니다.
