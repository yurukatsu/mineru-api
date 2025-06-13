import os
import tempfile
import zipfile
import io
from typing import Dict, Optional, Any
from pathlib import Path

from celery import Celery, Task
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

celery_app = Celery(
    "mineru_worker",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,
)

app = FastAPI(
    title="MinERU API", description="PDF processing API using MinERU and Celery"
)


class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str


class TaskStatus(BaseModel):
    task_id: str
    status: str
    progress: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    stage: Optional[str] = None


@celery_app.task(bind=True)
def process_pdf_task(self: Task, file_path: str, filename: str):
    try:
        from api.services import create_pdf_processor

        self.update_state(
            state="PROCESSING",
            meta={"progress": 0.0, "stage": "Starting PDF processing"},
        )

        # Create output directory for this task
        output_dir = f"/tmp/shared/{self.request.id}"
        os.makedirs(output_dir, exist_ok=True)

        # Read PDF file
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()

        self.update_state(
            state="PROCESSING",
            meta={"progress": 0.2, "stage": "Initializing processor"},
        )

        # Create processor with output directory
        processor = create_pdf_processor(output_dir=output_dir)

        self.update_state(
            state="PROCESSING",
            meta={"progress": 0.3, "stage": "Analyzing PDF structure"},
        )

        # Process PDF with progress callback
        def progress_callback(progress: float, stage: str):
            self.update_state(
                state="PROCESSING", meta={"progress": progress, "stage": stage}
            )

        result_obj = processor.process_pdf_bytes(pdf_bytes, filename, progress_callback)

        self.update_state(
            state="PROCESSING", meta={"progress": 0.9, "stage": "Finalizing results"}
        )

        # Convert result to dictionary
        result = {
            "filename": result_obj.filename,
            "pages": result_obj.pages,
            "markdown_content": result_obj.markdown_content,
            "parse_method": result_obj.parse_method,
            "processing_time": result_obj.processing_time,
            "file_size": result_obj.file_size,
            "output_files": result_obj.output_files,
            "image_files": getattr(result_obj, "image_files", {}),
            "content_list_summary": len(result_obj.content_list)
            if result_obj.content_list
            else 0,
        }

        # Clean up temporary file
        if os.path.exists(file_path):
            os.remove(file_path)

        return result

    except Exception as exc:
        # Clean up temporary file on error
        if os.path.exists(file_path):
            os.remove(file_path)

        import traceback

        self.update_state(
            state="FAILURE",
            meta={
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "exc_type": type(exc).__name__,
            },
        )
        raise


@app.post("/start", response_model=TaskResponse)
async def start_task(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    file_content = await file.read()

    # Use shared temp directory for cross-container file access
    shared_temp_dir = "/tmp/shared"
    os.makedirs(shared_temp_dir, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        delete=False, suffix=".pdf", dir=shared_temp_dir
    ) as temp_file:
        temp_file.write(file_content)
        temp_file_path = temp_file.name

    task = process_pdf_task.delay(temp_file_path, file.filename)

    return TaskResponse(
        task_id=task.id, status="queued", message="Task started successfully"
    )


@app.get("/status/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    try:
        task_result = celery_app.AsyncResult(task_id)

        match task_result.state:
            case "PENDING":
                status = "queued"
                progress = None
                result = None
                error = None
                traceback = None
                stage = None
            case "PROCESSING":
                status = "processing"
                meta = task_result.info or {}
                progress = meta.get("progress")
                result = None
                error = None
                traceback = None
                stage = meta.get("stage")
            case "SUCCESS":
                status = "completed"
                progress = 1.0
                result_data = task_result.result
                if result_data and isinstance(result_data, dict):
                    result = {
                        k: v for k, v in result_data.items() if k != "markdown_content"
                    }
                else:
                    result = result_data
                error = None
                traceback = None
                stage = "Completed"
            case "FAILURE":
                status = "failed"
                progress = None
                result = None
                if isinstance(task_result.info, dict):
                    meta = task_result.info
                    error = meta.get("error", "Unknown error")
                    traceback = meta.get("traceback")
                else:
                    error = (
                        str(task_result.info) if task_result.info else "Unknown error"
                    )
                    traceback = None
                stage = "Failed"
            case "REVOKED":
                status = "cancelled"
                progress = None
                result = None
                error = "Task was cancelled"
                traceback = None
                stage = "Cancelled"
            case _:
                status = task_result.state.lower()
                progress = None
                result = None
                error = None
                traceback = None
                stage = None

        return TaskStatus(
            task_id=task_id,
            status=status,
            progress=progress,
            result=result,
            error=error,
            traceback=traceback,
            stage=stage,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving task status: {str(e)}"
        )


@app.delete("/stop/{task_id}", response_model=TaskResponse)
async def stop_task(task_id: str):
    try:
        celery_app.control.revoke(task_id, terminate=True)

        return TaskResponse(
            task_id=task_id, status="cancelling", message="Task cancellation requested"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error stopping task: {str(e)}")


@app.get("/tasks")
async def list_tasks():
    try:
        active_tasks = celery_app.control.inspect().active()
        scheduled_tasks = celery_app.control.inspect().scheduled()

        return {"active_tasks": active_tasks, "scheduled_tasks": scheduled_tasks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving tasks: {str(e)}")


@app.get("/workers")
async def get_workers():
    try:
        stats = celery_app.control.inspect().stats()
        return {"workers": stats}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving workers: {str(e)}"
        )


@app.get("/result/{task_id}")
async def get_task_result(task_id: str):
    try:
        task_result = celery_app.AsyncResult(task_id)

        if task_result.state != "SUCCESS":
            raise HTTPException(
                status_code=404, detail="Task not completed or not found"
            )

        return task_result.result

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving task result: {str(e)}"
        )


@app.get("/download/{task_id}")
async def download_task_results(task_id: str):
    """Download all task results as a ZIP file including images"""
    try:
        task_result = celery_app.AsyncResult(task_id)

        if task_result.state != "SUCCESS":
            raise HTTPException(
                status_code=404, detail="Task not completed or not found"
            )

        result = task_result.result
        output_files = result.get("output_files", {})
        image_files = result.get("image_files", {})

        if not output_files and not image_files:
            raise HTTPException(status_code=404, detail="No output files found")

        # Create ZIP in memory
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
            # Add each output file to ZIP
            for file_type, file_path in output_files.items():
                if file_path and os.path.exists(file_path):
                    file_obj = Path(file_path)
                    zipf.write(file_path, file_obj.name)

            # Add image files to ZIP
            for image_path in image_files.values():
                if image_path and os.path.exists(image_path):
                    image_obj = Path(image_path)
                    # Create images folder in ZIP
                    zipf.write(image_path, f"images/{image_obj.name}")

        zip_buffer.seek(0)

        # Generate filename for download
        filename = result.get("filename", "output")
        zip_filename = f"{Path(filename).stem}_results.zip"

        return StreamingResponse(
            io.BytesIO(zip_buffer.read()),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={zip_filename}"},
        )

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error downloading files: {str(e)}"
        )


@app.get("/download/{task_id}/{file_type}")
async def download_single_file(task_id: str, file_type: str):
    """Download a specific file from task results"""
    try:
        task_result = celery_app.AsyncResult(task_id)

        if task_result.state != "SUCCESS":
            raise HTTPException(
                status_code=404, detail="Task not completed or not found"
            )

        result = task_result.result
        output_files = result.get("output_files", {})
        image_files = result.get("image_files", {})

        file_path = None

        # Check in output_files first
        if file_type in output_files:
            file_path = output_files[file_type]
        # Check in image_files if not found in output_files
        elif file_type in image_files:
            file_path = image_files[file_type]
        else:
            raise HTTPException(
                status_code=404, detail=f"File type '{file_type}' not found"
            )

        if not file_path or not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

        file_obj = Path(file_path)

        def file_generator():
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    yield chunk

        # Determine media type based on file extension
        media_type = "application/octet-stream"
        if file_obj.suffix == ".pdf":
            media_type = "application/pdf"
        elif file_obj.suffix == ".md":
            media_type = "text/markdown"
        elif file_obj.suffix == ".json":
            media_type = "application/json"
        elif file_obj.suffix.lower() in [".jpg", ".jpeg"]:
            media_type = "image/jpeg"
        elif file_obj.suffix.lower() == ".png":
            media_type = "image/png"
        elif file_obj.suffix.lower() == ".gif":
            media_type = "image/gif"
        elif file_obj.suffix.lower() == ".webp":
            media_type = "image/webp"
        elif file_obj.suffix.lower() == ".svg":
            media_type = "image/svg+xml"
        elif file_obj.suffix.lower() == ".bmp":
            media_type = "image/bmp"
        elif file_obj.suffix.lower() == ".tiff":
            media_type = "image/tiff"

        return StreamingResponse(
            file_generator(),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={file_obj.name}"},
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error downloading file: {str(e)}")


@app.get("/images/{task_id}")
async def list_task_images(task_id: str):
    """List all image files from task results"""
    try:
        task_result = celery_app.AsyncResult(task_id)

        if task_result.state != "SUCCESS":
            raise HTTPException(
                status_code=404, detail="Task not completed or not found"
            )

        result = task_result.result
        image_files = result.get("image_files", {})

        # Return list of available images with metadata
        image_list = []
        for image_name, image_path in image_files.items():
            if image_path and os.path.exists(image_path):
                file_obj = Path(image_path)
                stat = file_obj.stat()
                image_list.append(
                    {
                        "name": image_name,
                        "filename": file_obj.name,
                        "size": stat.st_size,
                        "extension": file_obj.suffix.lower(),
                        "download_url": f"/download/{task_id}/{image_name}",
                    }
                )

        return {
            "task_id": task_id,
            "image_count": len(image_list),
            "images": image_list,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing images: {str(e)}")


@app.get("/")
async def root():
    return {
        "message": "MinerU PDF Processing API with Celery",
        "version": "1.0.0",
        "celery_broker": celery_app.conf.broker_url,
        "celery_backend": celery_app.conf.result_backend,
    }
