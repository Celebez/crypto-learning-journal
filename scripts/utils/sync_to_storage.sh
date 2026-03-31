#!/bin/bash
# Hermes Learning System - Triple Storage Sync
# Run after each trading cycle to sync learning data
#
# Usage:
#   bash sync_to_storage.sh           # Sync to all (Redis + Supabase + D1)
#   bash sync_to_storage.sh --redis   # Redis only (fastest)
#   bash sync_to_storage.sh --check   # Check sync status

set -e
SYNC_DIR="$HOME/hermes_learning_sync"

case "${1:---sync}" in
    --sync)
        echo "=== Syncing to Redis + Supabase ==="
        cd "$SYNC_DIR" && python3 sync_learning.py --sync
        echo ""
        echo "=== Syncing to Cloudflare D1 ==="
        cd "$SYNC_DIR" && python3 sync_cloudflare.py --sync
        ;;
    --redis)
        cd "$SYNC_DIR" && python3 sync_learning.py --sync-redis
        ;;
    --supabase)
        cd "$SYNC_DIR" && python3 sync_learning.py --sync-supabase
        ;;
    --d1)
        cd "$SYNC_DIR" && python3 sync_cloudflare.py --sync
        ;;
    --check)
        echo "--- Redis ---"
        redis-cli ping 2>/dev/null && echo "OK" || echo "DOWN"
        cd "$SYNC_DIR" && python3 sync_cloudflare.py --status 2>/dev/null
        ;;
    *)
        echo "Usage: $0 [--sync|--redis|--supabase|--d1|--check]"
        ;;
esac
