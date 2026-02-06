"""Celery tasks for audio processing"""

from celery import Task
from celery_app import celery_app
from wazz_shared.database import SessionLocal
from wazz_shared.models import AudioProcessingJob
from wazz_shared.usage_tracking import track_processing_complete
from clearvoice import ClearVoice
import os
import traceback
from datetime import datetime, timezone
from wazz_shared.config import get_shared_settings

settings = get_shared_settings()


class DatabaseTask(Task):
    """Base task with database session and model management"""
    _db = None
    _cv_model = None

    @property
    def db(self):
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    @property
    def cv_model(self):
        """ClearVoice model cached per worker process — loaded once, reused across tasks."""
        if self._cv_model is None:
            self._cv_model = ClearVoice(
                task='speech_enhancement',
                model_names=[settings.clearvoice_model_name]
            )
        return self._cv_model

    def after_return(self, *args, **kwargs):
        if self._db is not None:
            self._db.close()
            self._db = None


@celery_app.task(base=DatabaseTask, bind=True, name='tasks.process_audio_task')
def process_audio_task(self, job_id: str):
    """
    Process audio file with ClearVoice noise reduction

    Args:
        job_id: UUID of the AudioProcessingJob

    Returns:
        dict: Processing result with job_id, status, and output_path
    """
    db = self.db

    # Step 1: Fetch job from database
    job = db.query(AudioProcessingJob).filter(
        AudioProcessingJob.job_id == job_id
    ).first()

    if not job:
        raise ValueError(f"Job {job_id} not found")

    try:
        # Step 2: Update status to processing
        job.status = "processing"
        job.started_at = datetime.now(timezone.utc)
        job.progress = 5.0
        job.processing_type = "speech_enhancement"
        db.commit()

        # Step 3: Validate input file exists
        if not os.path.exists(job.input_file_path):
            raise FileNotFoundError(f"Input file not found: {job.input_file_path}")

        # Step 4: Setup output directory and path
        output_dir = os.path.abspath(settings.output_dir)
        os.makedirs(output_dir, exist_ok=True)
        output_filename = f"processed_{job.filename}"
        final_output_path = os.path.join(output_dir, output_filename)

        job.progress = 10.0
        db.commit()

        # Step 5: Get cached ClearVoice model (loaded once per worker)
        cv = self.cv_model

        job.progress = 20.0
        db.commit()

        # Step 6: Process audio
        # Note: ClearVoice doesn't support progress callbacks, so we update at key points
        job.progress = 50.0
        db.commit()

        # Get list of files before processing to detect new files
        files_before = set(os.listdir(output_dir)) if os.path.exists(output_dir) else set()

        cv(
            input_path=job.input_file_path,
            online_write=True,
            output_path=output_dir
        )

        job.progress = 90.0
        db.commit()

        # Step 7: Handle output file naming
        # ClearVoice/MossFormer2 creates files in a model subdirectory
        model_output_dir = os.path.join(output_dir, settings.clearvoice_model_name)

        if os.path.exists(model_output_dir) and os.path.isdir(model_output_dir):
            # Look for audio files in the model subdirectory
            output_files = [f for f in os.listdir(model_output_dir)
                          if f.endswith(('.wav', '.mp3', '.flac', '.m4a', '.ogg'))]

            if not output_files:
                raise FileNotFoundError(
                    f"No audio files found in {model_output_dir}. "
                    f"Files present: {os.listdir(model_output_dir)}"
                )

            # Get the most recently modified file (should be the one we just created)
            output_files.sort(key=lambda f: os.path.getmtime(os.path.join(model_output_dir, f)), reverse=True)
            actual_output_path = os.path.join(model_output_dir, output_files[0])

        else:
            # Fallback: look in root output directory
            files_after = set(os.listdir(output_dir))
            new_files = files_after - files_before

            if not new_files:
                raise FileNotFoundError(
                    f"No new output file created in {output_dir}. "
                    f"Files in directory: {list(files_after)}"
                )

            output_file = new_files.pop()
            actual_output_path = os.path.join(output_dir, output_file)

        # Move the file to our desired output path
        import shutil
        shutil.move(actual_output_path, final_output_path)

        # Step 8: Update job as completed
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.progress = 100.0
        job.output_file_path = final_output_path

        # Calculate processing time and output file size
        processing_time = (job.completed_at - job.started_at).total_seconds() if job.started_at else 0.0
        output_file_size = float(os.path.getsize(final_output_path)) if os.path.exists(final_output_path) else 0.0

        db.commit()

        # Track successful processing for usage statistics
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
        # Step 9: Handle errors
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        job.status = "failed"
        job.error_message = error_msg
        job.completed_at = datetime.now(timezone.utc)

        # Calculate processing time even for failed jobs
        processing_time = (job.completed_at - job.started_at).total_seconds() if job.started_at else 0.0

        db.commit()

        # Track failed processing for usage statistics
        track_processing_complete(
            db=db,
            user_id=job.user_id,
            guest_id=job.guest_id,
            processing_time=processing_time,
            output_file_size=0.0,
            success=False
        )

        # Re-raise to mark task as failed in Celery
        raise


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
