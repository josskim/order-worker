# Railway deployment

`order-worker` can run on Railway as scheduled cron services instead of a local Windows task.

## Services

Create separate Railway services from the same GitHub repository when you want separate schedules.

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
  - `ORDER_WORKER_INVOICE_TYPE=real`
  - `ORDER_WORKER_RUNTIME_DIR=/tmp/order-worker`
  - `ORDER_WORKER_HEADLESS=1`

Railway evaluates cron schedules in UTC. Korea Standard Time is UTC+9, so subtract 9 hours from the local time.

## Required variables

Register production API URLs and tokens in Railway Variables. Do not commit real secrets.

```env
INTRANET_API_URL=https://YOUR_INTRAnet_DOMAIN/api/order-import
INTRANET_LOG_API_URL=https://YOUR_INTRAnet_DOMAIN/api/order-import/log
INTRANET_INVOICE_EXPORT_API_URL=https://YOUR_INTRAnet_DOMAIN/api/invoice-export/file
INTRANET_INVOICE_UPLOAD_MARK_API_URL=https://YOUR_INTRAnet_DOMAIN/api/invoice-export/mark-uploaded
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
  - `invoices` -> `python -m order_worker.main upload-invoices --all --type real`
  - `sites` -> `python -m order_worker.main sites`

## Notes

- Download, archive, log, and lock files are written to `/tmp/order-worker` by default on Railway.
- `/tmp` is ephemeral, which is fine because imported files are uploaded to the intranet and logs are posted to the intranet/Telegram.
- If you need long-term file retention, attach a Railway volume and set `ORDER_WORKER_RUNTIME_DIR=/data/order-worker`.
