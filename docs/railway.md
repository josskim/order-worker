# Railway deployment

`order-worker` can run on Railway as scheduled cron services instead of a local Windows task.

## Services

Create separate Railway services from the same GitHub repository when you want separate schedules.

For intranet button-triggered runs, use two fixed services:

- `order-worker-collect`: `ORDER_WORKER_TASK=collect-job`
- `order-worker-invoices`: `ORDER_WORKER_TASK=invoices-job`

The intranet sets a unique `ORDER_WORKER_JOB_ID` plus an
`ORDER_WORKER_JOB_TASK`, then redeploys the matching service. Invoice buttons
use `invoices-real` and `invoices-fake`, so actual shipping invoices and fake
invoices are never run implicitly as one operation. Repeated deployments with
an already completed job ID exit without running vendor automation again.

### Order collection

- Source: `josskim/order-worker`
- Cron schedule: weekdays during business hours, for example `30 23 * * 0-4` for 08:30 KST on weekdays
- Variables:
  - `ORDER_WORKER_TASK=collect`
  - `ORDER_WORKER_RUNTIME_DIR=/tmp/order-worker`
  - `ORDER_WORKER_HEADLESS=1`

### Invoice upload

- Source: `josskim/order-worker`
- Cron schedule: set to the desired shipping-upload time
- Variables:
  - `ORDER_WORKER_TASK=invoices`
  - `ORDER_WORKER_RUNTIME_DIR=/tmp/order-worker`
  - `ORDER_WORKER_HEADLESS=1`

The legacy scheduled invoice command runs `real` followed by `fake`. The
intranet does not use that combined command: the `출고송장실행` button requests
only `invoices-real`, and the `가송장실행` button requests only
`invoices-fake`. Because both buttons redeploy the same invoice service, the
intranet job queue prevents either invoice task from starting while another
invoice task is queued or running.

Railway evaluates cron schedules in UTC. Korea Standard Time is UTC+9, so subtract 9 hours from the local time.

## Required variables

Register production API URLs and tokens in Railway Variables. Do not commit real secrets.

```env
INTRANET_API_URL=https://YOUR_INTRANET_DOMAIN/api/order-import
INTRANET_LOG_API_URL=https://YOUR_INTRANET_DOMAIN/api/order-import/log
INTRANET_RUN_HISTORY_API_URL=https://YOUR_INTRANET_DOMAIN/api/order-worker/run-history
INTRANET_JOB_API_URL=https://YOUR_INTRANET_DOMAIN/api/order-worker/jobs/worker
ORDER_WORKER_RUN_HISTORY_TOKEN=...
INTRANET_INVOICE_EXPORT_API_URL=https://YOUR_INTRANET_DOMAIN/api/invoice-export/file
INTRANET_INVOICE_UPLOAD_MARK_API_URL=https://YOUR_INTRANET_DOMAIN/api/invoice-export/mark-uploaded
SISTER_ORDER_EXPORT_API_URL=https://prahashop.co.kr/api/seller/orders/export
SISTER_INVOICE_UPLOAD_API_URL=https://www.prahashop.co.kr/api/seller/invoice-upload
SISTER_ORDER_EXPORT_TOKEN=...
SISTER_INVOICE_UPLOAD_TOKEN=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## How it works

- `Dockerfile` uses the official Playwright Python image so Chromium is available in Railway builds.
- `railway.json` forces Dockerfile builds and disables restarts after a cron task exits.
- `scripts/railway-entrypoint.sh` maps `ORDER_WORKER_TASK` to the existing commands:
  - `collect` -> `python -m order_worker.main run --all`
  - `invoices` -> `python -m order_worker.main upload-invoices-all`
  - `collect-job` -> `python -m order_worker.main run-job --task collect`
  - `invoices-job` -> `python -m order_worker.main run-job --task $ORDER_WORKER_JOB_TASK`
  - `sites` -> `python -m order_worker.main sites`

## Notes

- Download, archive, log, and lock files are written to `/tmp/order-worker` by default on Railway.
- `/tmp` is ephemeral. Invoice execution history is stored in the intranet DB.
- Each completed button request can upload again on the same day; vendor-side
  upload handling remains responsible for ignoring invoices already accepted.
- If you need long-term file retention, attach a Railway volume and set `ORDER_WORKER_RUNTIME_DIR=/data/order-worker`.
