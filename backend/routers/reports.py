# -*- coding: utf-8 -*-
"""
routers/reports.py — FastAPI router for dust-report submission and retrieval.

Endpoints
---------
POST /reports
    Accept a multipart form containing the image file plus GPS metadata.
    Pipeline (synchronous part):
      1. Validate form fields into DustReportCreate.
      2. Upload image to S3 (upload_and_sign).
      3. Build a DustReport and persist it in DynamoDB (create_report).
      4. Enqueue background task: run vision AI → update DynamoDB with result.
    Returns HTTP 201 with the initial DustReportResponse (status=pending).

GET /reports/{report_id}
    Return the current state of a single report (including any AI analysis).

GET /reports
    List reports, optionally filtered by status, with a configurable limit.

GET /reports/{report_id}/nearby
    Return other reports within the configured geo-radius of the given report.
"""

from __future__ import annotations

import logging
import mimetypes
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from config import get_settings
from models.report import (
    DustReport,
    DustReportCreate,
    DustReportResponse,
    ReportStatus,
)
from services.dynamodb_service import (
    DynamoDBServiceError,
    ReportNotFoundError,
    create_report,
    find_nearby_reports,
    get_report,
    list_reports,
    record_audit_event,
    update_report_analysis,
)
from services.s3_service import S3ServiceError, delete_object, upload_and_sign
from services.vision_service import analyse_image

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


# ---------------------------------------------------------------------------
# Background task: vision analysis
# ---------------------------------------------------------------------------

def _run_vision_analysis(report_id: str, image_bytes: bytes) -> None:
    """
    Background task: call the vision service then atomically update the report.

    Design rule: this function MUST NOT raise — any failure is logged and the
    report remains in 'pending' state (a reviewer can still action it manually).
    """
    logger.info("background: starting vision analysis for report '%s'", report_id)
    try:
        analysis = analyse_image(image_bytes)
        # Build a throwaway DustReport just to compute the priority score
        dummy = DustReport(report_id=report_id, latitude=0.0, longitude=0.0, analysis=analysis)
        score = dummy.compute_priority()

        update_report_analysis(report_id, analysis, priority_score=score)

        logger.info(
            "background: analysis saved for '%s' — score=%.1f, status=analysed",
            report_id,
            score,
        )
    except Exception as exc:  # noqa: BLE001 — intentional broad catch in background task
        logger.error(
            "background: vision analysis failed for report '%s': %s",
            report_id,
            exc,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# POST /reports
# ---------------------------------------------------------------------------

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DustReportResponse,
    summary="Submit a new dust-pollution report",
    description=(
        "Accepts a multipart form with an image file and GPS coordinates. "
        "The image is stored in S3; the report record is persisted in DynamoDB. "
        "Vision AI analysis runs asynchronously in the background."
    ),
)
async def submit_report(
    background_tasks: BackgroundTasks,
    # Image file
    image: UploadFile = File(..., description="Photo of the pollution source (JPEG/PNG)"),
    # Form fields (mirrors DustReportCreate)
    latitude: float = Form(..., ge=-90, le=90, description="GPS latitude"),
    longitude: float = Form(..., ge=-180, le=180, description="GPS longitude"),
    address: Optional[str] = Form(None, max_length=500, description="Human-readable address"),
    description: Optional[str] = Form(
        None, max_length=2000, description="Resident's own description of the issue"
    ),
    category: Optional[str] = Form(
        None, max_length=100, description="Resident-selected pollution category"
    ),
) -> DustReportResponse:
    """Submit a dust-pollution report with an image."""
    settings = get_settings()

    # 1. Validate form data
    _input = DustReportCreate(
        latitude=latitude,
        longitude=longitude,
        address=address,
        description=description,
        category=category,
    )

    # 2. Read image bytes
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded image file is empty.",
        )

    # Derive file extension from uploaded filename or content-type
    content_type: str = image.content_type or "image/jpeg"
    ext = (image.filename or "photo.jpg").rsplit(".", 1)[-1].lower()
    if ext not in {"jpg", "jpeg", "png", "webp", "gif", "bmp"}:
        guessed = mimetypes.guess_extension(content_type, strict=False) or ".jpg"
        ext = guessed.lstrip(".")

    # 3. Build the initial DustReport
    report = DustReport(
        latitude=_input.latitude,
        longitude=_input.longitude,
        address=_input.address,
        description=_input.description,
        status=ReportStatus.PENDING,
    )

    # 4. Upload image to S3
    s3_key: Optional[str] = None
    s3_bucket: Optional[str] = None
    try:
        s3_key, s3_bucket, signed_url = upload_and_sign(
            image_bytes,
            content_type,
            report_id=report.report_id,
            extension=ext,
        )
        report.s3_key = s3_key
        report.s3_bucket = s3_bucket
        report.image_url = signed_url
        logger.info("router: image uploaded → s3://%s/%s", s3_bucket, s3_key)
    except S3ServiceError as exc:
        logger.error("router: S3 upload failed for report '%s': %s", report.report_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Image upload failed: {exc}",
        ) from exc

    # 5. Persist report in DynamoDB
    try:
        create_report(report)
        logger.info("router: report '%s' persisted in DynamoDB", report.report_id)
    except DynamoDBServiceError as exc:
        # Roll back S3 upload to avoid orphaned objects
        if s3_key and s3_bucket:
            try:
                delete_object(s3_key, bucket=s3_bucket)
                logger.info("router: rolled back S3 object '%s'", s3_key)
            except Exception as rollback_exc:  # noqa: BLE001
                logger.warning("router: S3 rollback failed for '%s': %s", s3_key, rollback_exc)

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to save report: {exc}",
        ) from exc

    # 6. Record audit event (non-blocking)
    try:
        record_audit_event(
            event_type="report_submitted",
            report_id=report.report_id,
            details={
                "latitude": report.latitude,
                "longitude": report.longitude,
                "s3_key": s3_key,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("router: audit event failed for '%s': %s", report.report_id, exc)

    # 7. Enqueue background vision analysis
    background_tasks.add_task(_run_vision_analysis, report.report_id, image_bytes)
    logger.info("router: vision analysis enqueued for '%s'", report.report_id)

    return DustReportResponse.from_report(report)


# ---------------------------------------------------------------------------
# GET /reports/{report_id}
# ---------------------------------------------------------------------------

@router.get(
    "/{report_id}",
    response_model=DustReportResponse,
    summary="Get a single dust-pollution report",
    description="Retrieve the current state of a report, including any AI analysis results.",
)
def get_single_report(report_id: str) -> DustReportResponse:
    """Return the latest state of a dust-pollution report by ID."""
    try:
        report = get_report(report_id)
    except DynamoDBServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error: {exc}",
        ) from exc

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' not found.",
        )

    return DustReportResponse.from_report(report)


# ---------------------------------------------------------------------------
# GET /reports
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=list[DustReportResponse],
    summary="List dust-pollution reports",
    description=(
        "Return a list of reports, sorted newest-first. "
        "Optionally filter by lifecycle status and limit the result count."
    ),
)
def list_all_reports(
    status_filter: Optional[ReportStatus] = Query(
        None,
        alias="status",
        description="Filter by report status: pending | analysed | linked | closed",
    ),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of reports to return"),
) -> list[DustReportResponse]:
    """List reports, newest first, with optional status filter."""
    try:
        reports = list_reports(limit=limit, status=status_filter)
    except DynamoDBServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error: {exc}",
        ) from exc

    return [DustReportResponse.from_report(r) for r in reports]


# ---------------------------------------------------------------------------
# GET /reports/{report_id}/nearby
# ---------------------------------------------------------------------------

@router.get(
    "/{report_id}/nearby",
    response_model=list[DustReportResponse],
    summary="Find nearby reports for a given report",
    description=(
        "Return other reports within the configured geo-radius of the given "
        "report's location, excluding the report itself."
    ),
)
def get_nearby_reports(report_id: str) -> list[DustReportResponse]:
    """Return nearby reports for a given report ID."""
    settings = get_settings()

    try:
        report = get_report(report_id)
    except DynamoDBServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error: {exc}",
        ) from exc

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' not found.",
        )

    try:
        nearby = find_nearby_reports(
            latitude=report.latitude,
            longitude=report.longitude,
            radius_km=settings.GEO_NEARBY_RADIUS_KM,
            time_window_days=settings.GEO_NEARBY_TIME_WINDOW_DAYS,
            exclude_report_id=report_id,
        )
    except DynamoDBServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Geo-search failed: {exc}",
        ) from exc

    return [DustReportResponse.from_report(r) for r in nearby]
