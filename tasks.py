"""Celery tasks for audio processing"""

from celery import Task
from celery_app import celery_app
from wazz_shared.database import SessionLocal
from wazz_shared.models import AudioProcessingJob
from wazz_shared.usage_tracking import track_processing_complete
from clearvoice import ClearVoice
import os
import shutil
import zipfile
import traceback
from datetime import datetime, timezone
from wazz_shared.config import get_shared_settings

settings = get_shared_settings()

# Maps frontend processing_type to ClearVoice task and model
TASK_CONFIG = {
    "speech_enhancement": {
        "cv_task": "speech_enhancement",
        "model": settings.clearvoice_model_name,
        "multi_output": False,
    },
    "noise_reduction": {
        "cv_task": "speech_enhancement",
        "model": settings.clearvoice_model_name,
        "multi_output": False,
    },
    "speaker_separation": {
        "cv_task": "speech_separation",
        "model": settings.clearvoice_separation_model_name,
        "multi_output": True,
    },
}

AUDIO_EXTENSIONS = ('.wav', '.mp3', '.flac', '.m4a', '.ogg')


class DatabaseTask(Task):
    """Base task with database session and model management"""
    _db = None
    _cv_models = {}

    @property
    def db(self):
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    def get_cv_model(self, processing_type: str) -> ClearVoice:
        """Get or create a cached ClearVoice model for the given processing type."""
        config = TASK_CONFIG.get(processing_type)
        if not config:
            raise ValueError(f"Unsupported processing type: {processing_type}")

        cache_key = f"{config['cv_task']}_{config['model']}"
        if cache_key not in self._cv_models:
            self._cv_models[cache_key] = ClearVoice(
                task=config["cv_task"],
                model_names=[config["model"]],
            )
        return self._cv_models[cache_key]

    def after_return(self, *args, **kwargs):
        if self._db is not None:
            self._db.close()
            self._db = None


@celery_app.task(base=DatabaseTask, bind=True, name='tasks.process_audio_task')
def process_audio_task(self, job_id: str):
    """
    Process audio file with ClearVoice.

    Supports: speech_enhancement, noise_reduction, speaker_separation.
    Routes to the correct ClearVoice task/model based on job.processing_type.
    """
    db = self.db

    job = db.query(AudioProcessingJob).filter(
        AudioProcessingJob.job_id == job_id
    ).first()

    if not job:
        raise ValueError(f"Job {job_id} not found")

    try:
        processing_type = job.processing_type or "speech_enhancement"
        config = TASK_CONFIG.get(processing_type)

        if not config:
            raise ValueError(f"Unsupported processing type: {processing_type}")

        job.status = "processing"
        job.started_at = datetime.now(timezone.utc)
        job.progress = 5.0
        db.commit()

        if not os.path.exists(job.input_file_path):
            raise FileNotFoundError(f"Input file not found: {job.input_file_path}")

        output_dir = os.path.abspath(settings.output_dir)
        os.makedirs(output_dir, exist_ok=True)

        job.progress = 10.0
        db.commit()

        cv = self.get_cv_model(processing_type)

        job.progress = 20.0
        db.commit()

        job.progress = 50.0
        db.commit()

        # Run ClearVoice processing
        cv(
            input_path=job.input_file_path,
            online_write=True,
            output_path=output_dir
        )

        job.progress = 90.0
        db.commit()

        # Collect output files from model subdirectory
        model_output_dir = os.path.join(output_dir, config["model"])
        output_files = _find_output_files(model_output_dir, output_dir)

        if not output_files:
            raise FileNotFoundError(
                f"No output files produced by {config['model']}"
            )

        if config["multi_output"] and len(output_files) > 1:
            final_output_path = _zip_outputs(
                output_files, output_dir, job.filename
            )
        else:
            final_output_path = os.path.join(
                output_dir, f"processed_{job.filename}"
            )
            shutil.move(output_files[0], final_output_path)

        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.progress = 100.0
        job.output_file_path = final_output_path

        processing_time = (job.completed_at - job.started_at).total_seconds() if job.started_at else 0.0
        output_file_size = float(os.path.getsize(final_output_path)) if os.path.exists(final_output_path) else 0.0

        db.commit()

        track_processing_complete(
            db=db,
            user_id=job.user_id,
            guest_id=job.guest_id,
            processing_time=processing_time,
            output_file_size=output_file_size,
            success=True
        )

        return {
            "job_id": job_id,
            "status": "completed",
            "output_path": final_output_path
        }

    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        job.status = "failed"
        job.error_message = error_msg
        job.completed_at = datetime.now(timezone.utc)

        processing_time = (job.completed_at - job.started_at).total_seconds() if job.started_at else 0.0

        db.commit()

        track_processing_complete(
            db=db,
            user_id=job.user_id,
            guest_id=job.guest_id,
            processing_time=processing_time,
            output_file_size=0.0,
            success=False
        )

        raise


def _find_output_files(model_output_dir: str, output_dir: str) -> list[str]:
    """Find audio output files, checking model subdirectory first, then root."""
    if os.path.exists(model_output_dir) and os.path.isdir(model_output_dir):
        files = [
            os.path.join(model_output_dir, f)
            for f in os.listdir(model_output_dir)
            if f.endswith(AUDIO_EXTENSIONS)
        ]
        files.sort(key=os.path.getmtime, reverse=True)
        return files

    # Fallback: root output directory
    files = [
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if f.endswith(AUDIO_EXTENSIONS)
    ]
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def _zip_outputs(file_paths: list[str], output_dir: str, job_filename: str) -> str:
    """Zip multiple output files into a single archive."""
    base_name = os.path.splitext(job_filename)[0]
    zip_path = os.path.join(output_dir, f"separated_{base_name}.zip")

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, fp in enumerate(file_paths, 1):
            ext = os.path.splitext(fp)[1]
            arcname = f"speaker_{i}{ext}"
            zf.write(fp, arcname)

    # Clean up individual files
    for fp in file_paths:
        os.remove(fp)

    return zip_path


@celery_app.task(name='tasks.cleanup_expired_files')
def cleanup_expired_files():
    """
    Periodic task to clean up expired job files

    Deletes:
    - Input audio files
    - Output processed files
    - Database job records

    Runs daily at 2 AM (configured in celery_config.py)
    """
    db = SessionLocal()

    try:
        # Find jobs that have expired
        expired_jobs = db.query(AudioProcessingJob).filter(
            AudioProcessingJob.expires_at < datetime.now(timezone.utc)
        ).all()

        deleted_count = 0

        for job in expired_jobs:
            try:
                # Delete input file
                if job.input_file_path and os.path.exists(job.input_file_path):
                    os.remove(job.input_file_path)

                # Delete output file
                if job.output_file_path and os.path.exists(job.output_file_path):
                    os.remove(job.output_file_path)

                # Delete database record
                db.delete(job)
                deleted_count += 1

            except Exception as e:
                # Log error but continue with other jobs
                print(f"Error cleaning up job {job.job_id}: {str(e)}")

        db.commit()

        return {
            "deleted_count": deleted_count,
            "message": f"Successfully cleaned up {deleted_count} expired jobs"
        }

    except Exception as e:
        db.rollback()
        raise

    finally:
        db.close()
