#!/usr/bin/env sh
set -eu

runtime_dir="${ORDER_WORKER_RUNTIME_DIR:-/tmp/order-worker}"
export ORDER_WORKER_DOWNLOAD_DIR="${ORDER_WORKER_DOWNLOAD_DIR:-$runtime_dir/downloads}"
export ORDER_WORKER_ARCHIVE_DIR="${ORDER_WORKER_ARCHIVE_DIR:-$runtime_dir/archive}"
export ORDER_WORKER_LOG_DIR="${ORDER_WORKER_LOG_DIR:-$runtime_dir/logs}"
export ORDER_WORKER_LOCK_FILE="${ORDER_WORKER_LOCK_FILE:-$runtime_dir/order-worker.lock}"

mkdir -p "$ORDER_WORKER_DOWNLOAD_DIR" "$ORDER_WORKER_ARCHIVE_DIR" "$ORDER_WORKER_LOG_DIR" "$(dirname "$ORDER_WORKER_LOCK_FILE")"

task="${ORDER_WORKER_TASK:-${1:-sites}}"

case "$task" in
  sites)
    exec python -m order_worker.main sites
    ;;
  invoice-sites)
    exec python -m order_worker.main invoice-sites
    ;;
  collect)
    exec python -m order_worker.main run --all
    ;;
  invoices)
    exec python -m order_worker.main upload-invoices-all
    ;;
  custom)
    if [ -z "${ORDER_WORKER_COMMAND:-}" ]; then
      echo "ORDER_WORKER_COMMAND is required when ORDER_WORKER_TASK=custom" >&2
      exit 2
    fi
    exec sh -c "$ORDER_WORKER_COMMAND"
    ;;
  *)
    exec "$@"
    ;;
esac
