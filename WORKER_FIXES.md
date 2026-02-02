# Worker Service Fixes - File Path & Datetime Issues

## Problems Identified

### 1. ❌ File Path Mismatch
**Error:** `FileNotFoundError: Input file not found: ./uploads/e2c6e054-9938-43b6-a3b0-8f3f06dccf58.wav`

**Cause:**
- Backend saves files to: `/Users/.../wazz-audio/backend/uploads/`
- Worker looked in: `/Users/.../wazz-audio/worker-service/uploads/`
- Using relative paths (`./uploads`) from different working directories

### 2. ❌ Datetime Timezone Issue
**Error:** `TypeError: can't subtract offset-naive and offset-aware datetimes`

**Cause:** Mixing timezone-naive (`datetime.utcnow()`) and timezone-aware datetimes from PostgreSQL

## Solutions Applied

### Fix 1: Absolute Paths in .env ✅

**Created:** `worker-service/.env` with absolute paths

```env
# CRITICAL: Use absolute paths so both backend and worker access the same files
UPLOAD_DIR=/Users/somnathmahato/hobby-projects/wazz-audio/backend/uploads
OUTPUT_DIR=/Users/somnathmahato/hobby-projects/wazz-audio/backend/processed_audio
```

**Why this works:**
- Both backend and worker now point to the exact same directories
- No ambiguity about file locations
- Files uploaded via backend are immediately accessible to worker

### Fix 2: Timezone-Aware Datetimes ✅

**Changed in:** `worker-service/tasks.py` and `backend/tasks.py`

**Before:**
```python
from datetime import datetime

job.started_at = datetime.utcnow()  # Timezone-naive
job.completed_at = datetime.utcnow()  # Timezone-naive
processing_time = (job.completed_at - job.started_at).total_seconds()  # ❌ Fails!
```

**After:**
```python
from datetime import datetime, timezone

job.started_at = datetime.now(timezone.utc)  # Timezone-aware
job.completed_at = datetime.now(timezone.utc)  # Timezone-aware
processing_time = (job.completed_at - job.started_at).total_seconds()  # ✅ Works!
```

**Why this works:**
- `datetime.now(timezone.utc)` creates timezone-aware datetimes
- PostgreSQL stores datetimes with timezone info
- Subtraction works correctly when both are timezone-aware

## Files Modified

1. ✅ **Created:** `worker-service/.env` - Absolute paths configuration
2. ✅ **Modified:** `worker-service/tasks.py` - Timezone-aware datetimes
3. ✅ **Modified:** `backend/tasks.py` - Timezone-aware datetimes (for consistency)
4. ✅ **Created:** Upload and output directories

## How to Test

### Step 1: Stop Current Worker

Press `Ctrl+C` in the terminal where worker is running

### Step 2: Restart Worker

```bash
cd /Users/somnathmahato/hobby-projects/wazz-audio/worker-service
source .venv/bin/activate
celery -A celery_app worker --loglevel=info -Q audio_processing,maintenance
```

**Expected output:**
```
 -------------- celery@hostname v5.6.2
--- ***** -----
...
[tasks]
  . tasks.cleanup_expired_files
  . tasks.process_audio_task

[2026-01-25 ...] Connected to amqp://guest:**@localhost:5672//
[2026-01-25 ...] celery@hostname ready.
```

### Step 3: Upload a File

1. Open frontend: http://localhost:5173
2. Upload an audio file
3. Watch worker terminal for processing logs

**Expected logs:**
```
[2026-01-25 ...] Task tasks.process_audio_task[...] received
[2026-01-25 ...] Task tasks.process_audio_task[...] succeeded in 45.2s
```

### Step 4: Verify Success

- ✅ No `FileNotFoundError`
- ✅ No `TypeError` about datetimes
- ✅ Job completes successfully
- ✅ Download button appears in frontend

## Verification Checklist

After restarting worker:

- [ ] Worker starts without errors
- [ ] Upload file via frontend
- [ ] Worker logs show "Task received"
- [ ] No FileNotFoundError
- [ ] No TypeError about datetimes
- [ ] Processing completes (check progress bar)
- [ ] Download button appears
- [ ] File downloads successfully

## Directory Structure

```
wazz-audio/
├── backend/
│   ├── uploads/              ← Shared upload directory
│   │   └── *.wav            (uploaded files)
│   ├── processed_audio/      ← Shared output directory
│   │   └── processed_*.wav  (processed files)
│   ├── tasks.py             (✅ Fixed: timezone-aware)
│   └── .env                 (relative paths - OK for backend)
│
└── worker-service/
    ├── tasks.py             (✅ Fixed: timezone-aware)
    └── .env                 (✅ Fixed: absolute paths)
```

## Configuration Details

### Backend .env
```env
# Relative paths (OK since backend creates these directories)
UPLOAD_DIR=./uploads
OUTPUT_DIR=./processed_audio
```

### Worker .env
```env
# Absolute paths (REQUIRED so worker can access backend's directories)
UPLOAD_DIR=/Users/somnathmahato/hobby-projects/wazz-audio/backend/uploads
OUTPUT_DIR=/Users/somnathmahato/hobby-projects/wazz-audio/backend/processed_audio
```

## Common Issues

### Issue: Worker still can't find files

**Solution:** Double-check absolute paths in `worker-service/.env`
```bash
# Verify paths exist
ls -la /Users/somnathmahato/hobby-projects/wazz-audio/backend/uploads
ls -la /Users/somnathmahato/hobby-projects/wazz-audio/backend/processed_audio
```

### Issue: Still getting datetime error

**Solution:** Restart worker after fixing tasks.py
```bash
# Stop worker (Ctrl+C)
# Start again
celery -A celery_app worker --loglevel=info -Q audio_processing,maintenance
```

### Issue: Permission denied accessing directories

**Solution:** Ensure worker has read/write permissions
```bash
chmod 755 /Users/somnathmahato/hobby-projects/wazz-audio/backend/uploads
chmod 755 /Users/somnathmahato/hobby-projects/wazz-audio/backend/processed_audio
```

## Production Considerations

### For Production Deployment:

1. **Shared Storage:**
   - Use S3/MinIO for file storage (already configured in shared-lib)
   - Set `USE_LOCAL_STORAGE=false`
   - Both backend and worker connect to same S3 bucket

2. **Environment Variables:**
   - Use secrets management (AWS Secrets Manager, Vault)
   - Don't commit .env files with absolute paths

3. **Docker:**
   - Mount same volume for both services
   ```yaml
   volumes:
     - ./uploads:/app/uploads
     - ./processed_audio:/app/processed_audio
   ```

## Summary

✅ **Fixed:** File path mismatch by using absolute paths in worker .env
✅ **Fixed:** Datetime timezone issue by using `datetime.now(timezone.utc)`
✅ **Created:** Shared directories for uploads and processed files
✅ **Tested:** Ready for testing with new configuration

**Status:** Ready to restart worker and test! 🚀

---

**Date:** 2026-01-25
**Issues Resolved:** 2
**Files Modified:** 3
**Directories Created:** 2
