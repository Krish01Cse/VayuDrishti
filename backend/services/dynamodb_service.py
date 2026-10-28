# -*- coding: utf-8 -*-
"""
services/dynamodb_service.py — DynamoDB persistence service for VayuDrishti.

Responsibilities
----------------
1. DustReports CRUD:
   - create_report: save a newly submitted DustReport item to DynamoDB.
   - get_report: retrieve a DustReport by its unique report_id.
   - update_report: replace/update an entire DustReport item.
   - update_report_analysis: atomically record Vision AI analysis results,
     computed priority score, and update report status (e.g. 'analysed').
   - update_report_case_id: link a report to an IncidentCase.
   - update_report_status: update lifecycle status.
   - delete_report: remove a report item (used in rollback/testing).

2. Reports Queries & Geo-Search:
   - list_reports: scan reports with optional status filtering and pagination.
   - get_reports_by_case: query reports linked to a case using GSI 'case_id-index'.
   - find_nearby_reports: bounding-box scan + Haversine distance filtering for
     retrieving related reports within a geographic radius (km) and time window.
     (Note: DynamoDB has no native geospatial indexing; this uses bounding-box
     filtering with post-scan distance evaluation suited for demo scale).

3. AuditEvents (Supporting Table):
   - record_audit_event: append an immutable audit log entry.
   - get_audit_events_for_case: query chronological audit log via
     'case_id-timestamp-index' GSI.

Design notes
------------
- Single cached boto3 resource & client via @lru_cache.
- Honors USE_LOCALSTACK=true from config.py without code modifications.
- AWS/Boto exceptions are caught and wrapped in DynamoDBServiceError /
  ReportNotFoundError so callers never need to import botocore directly.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import BotoCoreError, ClientError

try:
    from config import Settings, get_settings
    from models.report import DustReport, ReportStatus, VisualAnalysis
except ImportError:
    from backend.config import Settings, get_settings
    from backend.models.report import DustReport, ReportStatus, VisualAnalysis

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class DynamoDBServiceError(RuntimeError):
    """Base exception for all DynamoDB service failures."""


class ReportNotFoundError(DynamoDBServiceError):
    """Raised when an operation targets a report_id that does not exist."""


# ---------------------------------------------------------------------------
# Client & Resource Factory (Cached per Process)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_dynamodb_resource(settings_hash: int):  # noqa: ARG001
    """Return a cached boto3 DynamoDB resource configured from Settings."""
    settings: Settings = get_settings()
    return boto3.resource("dynamodb", **settings.boto3_kwargs)


@lru_cache(maxsize=1)
def _get_dynamodb_client(settings_hash: int):  # noqa: ARG001
    """Return a cached boto3 DynamoDB client configured from Settings."""
    settings: Settings = get_settings()
    return boto3.client("dynamodb", **settings.boto3_kwargs)


def _resource():
    """Convenience accessor for the cached DynamoDB resource."""
    settings = get_settings()
    return _get_dynamodb_resource(id(settings))


def _client():
    """Convenience accessor for the cached DynamoDB client."""
    settings = get_settings()
    return _get_dynamodb_client(id(settings))


def _get_reports_table():
    """Return the DynamoDB Table resource for DustReports."""
    settings = get_settings()
    return _resource().Table(settings.DYNAMODB_TABLE_DUST_REPORTS)


def _get_audit_table():
    """Return the DynamoDB Table resource for AuditEvents."""
    settings = get_settings()
    return _resource().Table(settings.DYNAMODB_TABLE_AUDIT_EVENTS)


# ---------------------------------------------------------------------------
# Geospatial Utility Functions
# ---------------------------------------------------------------------------

def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two GPS coordinates in kilometers.

    Uses the standard Haversine formula (Earth radius = 6371.0 km).
    """
    r_earth = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r_earth * c


def get_bounding_box(
    lat: float, lon: float, radius_km: float
) -> tuple[float, float, float, float]:
    """
    Compute (min_lat, max_lat, min_lon, max_lon) bounding box for a given center & radius.
    """
    r_earth = 6371.0
    delta_lat = math.degrees(radius_km / r_earth)

    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-6:
        delta_lon = 180.0
    else:
        delta_lon = math.degrees(radius_km / (r_earth * cos_lat))

    min_lat = max(-90.0, lat - delta_lat)
    max_lat = min(90.0, lat + delta_lat)
    min_lon = max(-180.0, lon - delta_lon)
    max_lon = min(180.0, lon + delta_lon)
    return min_lat, max_lat, min_lon, max_lon


# ---------------------------------------------------------------------------
# Mock mode — in-memory store (no AWS needed)
# ---------------------------------------------------------------------------

def _is_mock() -> bool:
    """Return True when STORAGE_PROVIDER=mock."""
    return getattr(get_settings(), "STORAGE_PROVIDER", "aws").lower() == "mock"


# In-memory store: report_id -> DustReport
_MOCK_REPORTS: dict[str, "DustReport"] = {}


def _attach_fresh_image_url(report: Optional["DustReport"]) -> Optional["DustReport"]:
    """Ensure report has a fresh, valid presigned URL when fetched from DynamoDB."""
    if report is None:
        return None
    if not _is_mock() and report.s3_key:
        try:
            try:
                from services.s3_service import generate_signed_url
            except ImportError:
                from backend.services.s3_service import generate_signed_url
            report.image_url = generate_signed_url(report.s3_key, bucket=report.s3_bucket)
        except Exception as exc:
            logger.warning("dynamodb_service: failed to refresh presigned URL for '%s': %s", report.report_id, exc)
    return report


# ---------------------------------------------------------------------------
# DustReports CRUD Operations
# ---------------------------------------------------------------------------

def create_report(report: DustReport) -> DustReport:
    """
    Persist a new DustReport into the DustReports DynamoDB table.

    Parameters
    ----------
    report : DustReport
        The report instance to store.

    Returns
    -------
    DustReport
        The persisted report instance.

    Raises
    ------
    DynamoDBServiceError
        If writing to DynamoDB fails.
    """
    # ── Mock mode ────────────────────────────────────────────────────────
    if _is_mock():
        now = datetime.now(timezone.utc)
        if not report.created_at:
            report.created_at = now
        if not report.updated_at:
            report.updated_at = now
        _MOCK_REPORTS[report.report_id] = report
        logger.info("dynamodb_service [MOCK]: stored report '%s'", report.report_id)
        return report

    table = _get_reports_table()
    now = datetime.now(timezone.utc)
    if not report.created_at:
        report.created_at = now
    if not report.updated_at:
        report.updated_at = now

    item = report.to_dynamo_item()

    try:
        table.put_item(Item=item)
        logger.info("dynamodb_service: created report '%s'", report.report_id)
        return report
    except (ClientError, BotoCoreError) as exc:
        raise DynamoDBServiceError(
            f"Failed to create report '{report.report_id}': {exc}"
        ) from exc


def get_report(report_id: str) -> Optional[DustReport]:
    """
    Retrieve a DustReport by its unique report_id.

    Parameters
    ----------
    report_id : str
        Primary key partition identifier.

    Returns
    -------
    Optional[DustReport]
        The deserialized report if found, otherwise None.

    Raises
    ------
    DynamoDBServiceError
        If the query fails.
    """
    if _is_mock():
        return _MOCK_REPORTS.get(report_id)

    table = _get_reports_table()
    try:
        resp = table.get_item(Key={"report_id": report_id})
        item = resp.get("Item")
        if not item:
            logger.debug("dynamodb_service: report '%s' not found", report_id)
            return None
        return _attach_fresh_image_url(DustReport.from_dynamo_item(item))
    except (ClientError, BotoCoreError) as exc:
        raise DynamoDBServiceError(
            f"Failed to get report '{report_id}': {exc}"
        ) from exc


def update_report(report: DustReport) -> DustReport:
    """
    Update / overwrite an entire DustReport in DynamoDB.

    Refreshes updated_at timestamp before saving.

    Parameters
    ----------
    report : DustReport
        The updated report instance.

    Returns
    -------
    DustReport
        The saved report instance.
    """
    table = _get_reports_table()
    report.updated_at = datetime.now(timezone.utc)
    item = report.to_dynamo_item()

    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_exists(report_id)",
        )
        logger.info("dynamodb_service: updated report '%s'", report.report_id)
        return report
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ConditionalCheckFailedException":
            raise ReportNotFoundError(
                f"Report '{report.report_id}' does not exist"
            ) from exc
        raise DynamoDBServiceError(
            f"Failed to update report '{report.report_id}': {exc}"
        ) from exc
    except BotoCoreError as exc:
        raise DynamoDBServiceError(
            f"Failed to update report '{report.report_id}': {exc}"
        ) from exc


def update_report_analysis(
    report_id: str,
    analysis: VisualAnalysis,
    priority_score: Optional[float] = None,
    status: ReportStatus = ReportStatus.ANALYSED,
) -> DustReport:
    """
    Atomically update a report with Vision AI analysis results and priority score.

    Parameters
    ----------
    report_id : str
        The report identifier.
    analysis : VisualAnalysis
        Structured AI observation payload.
    priority_score : Optional[float]
        Priority score 0-100. If omitted, calculated via report heuristics.
    status : ReportStatus
        Target status, defaults to ReportStatus.ANALYSED.

    Returns
    -------
    DustReport
        The updated report item.

    Raises
    ------
    ReportNotFoundError
        If the report does not exist.
    DynamoDBServiceError
        If the update operation fails.
    """
    # ── Mock mode ────────────────────────────────────────────────────────
    if _is_mock():
        report = _MOCK_REPORTS.get(report_id)
        if report is None:
            raise ReportNotFoundError(f"Report '{report_id}' does not exist")
        if priority_score is None:
            dummy = DustReport(report_id=report_id, latitude=report.latitude,
                               longitude=report.longitude, analysis=analysis)
            score = dummy.compute_priority()
        else:
            score = min(max(float(priority_score), 0.0), 100.0)
        report.analysis = analysis
        report.priority_score = score
        report.status = status
        report.updated_at = datetime.now(timezone.utc)
        _MOCK_REPORTS[report_id] = report
        logger.info("dynamodb_service [MOCK]: updated analysis for '%s'", report_id)
        return report

    table = _get_reports_table()

    # If priority score wasn't provided, compute standard score from analysis
    if priority_score is None:
        dummy = DustReport(
            report_id=report_id,
            latitude=0.0,
            longitude=0.0,
            analysis=analysis,
        )
        score = dummy.compute_priority()
    else:
        score = min(max(float(priority_score), 0.0), 100.0)

    now_iso = datetime.now(timezone.utc).isoformat()
    analysis_json = analysis.model_dump_json()
    status_val = status.value if isinstance(status, ReportStatus) else str(status)

    try:
        response = table.update_item(
            Key={"report_id": report_id},
            UpdateExpression=(
                "SET #analysis = :analysis, "
                "#priority_score = :priority_score, "
                "#status = :status, "
                "#updated_at = :updated_at"
            ),
            ConditionExpression="attribute_exists(report_id)",
            ExpressionAttributeNames={
                "#analysis": "analysis",
                "#priority_score": "priority_score",
                "#status": "status",
                "#updated_at": "updated_at",
            },
            ExpressionAttributeValues={
                ":analysis": analysis_json,
                ":priority_score": str(score),
                ":status": status_val,
                ":updated_at": now_iso,
            },
            ReturnValues="ALL_NEW",
        )
        logger.info(
            "dynamodb_service: updated analysis for report '%s' (score=%s)",
            report_id,
            score,
        )
        return DustReport.from_dynamo_item(response["Attributes"])
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ConditionalCheckFailedException":
            raise ReportNotFoundError(f"Report '{report_id}' does not exist") from exc
        raise DynamoDBServiceError(
            f"Failed to update analysis for report '{report_id}': {exc}"
        ) from exc
    except BotoCoreError as exc:
        raise DynamoDBServiceError(
            f"Failed to update analysis for report '{report_id}': {exc}"
        ) from exc


def update_report_case_id(
    report_id: str,
    case_id: str,
    status: ReportStatus = ReportStatus.LINKED,
) -> DustReport:
    """
    Link a report to an IncidentCase and mark status as LINKED.
    """
    table = _get_reports_table()
    now_iso = datetime.now(timezone.utc).isoformat()
    status_val = status.value if isinstance(status, ReportStatus) else str(status)

    try:
        response = table.update_item(
            Key={"report_id": report_id},
            UpdateExpression=(
                "SET #case_id = :case_id, "
                "#status = :status, "
                "#updated_at = :updated_at"
            ),
            ConditionExpression="attribute_exists(report_id)",
            ExpressionAttributeNames={
                "#case_id": "case_id",
                "#status": "status",
                "#updated_at": "updated_at",
            },
            ExpressionAttributeValues={
                ":case_id": case_id,
                ":status": status_val,
                ":updated_at": now_iso,
            },
            ReturnValues="ALL_NEW",
        )
        logger.info(
            "dynamodb_service: linked report '%s' to case '%s'",
            report_id,
            case_id,
        )
        return DustReport.from_dynamo_item(response["Attributes"])
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ConditionalCheckFailedException":
            raise ReportNotFoundError(f"Report '{report_id}' does not exist") from exc
        raise DynamoDBServiceError(
            f"Failed to link report '{report_id}' to case '{case_id}': {exc}"
        ) from exc
    except BotoCoreError as exc:
        raise DynamoDBServiceError(
            f"Failed to link report '{report_id}' to case '{case_id}': {exc}"
        ) from exc


def update_report_status(
    report_id: str,
    status: ReportStatus,
) -> DustReport:
    """
    Update the lifecycle status of a report.
    """
    table = _get_reports_table()
    now_iso = datetime.now(timezone.utc).isoformat()
    status_val = status.value if isinstance(status, ReportStatus) else str(status)

    try:
        response = table.update_item(
            Key={"report_id": report_id},
            UpdateExpression="SET #status = :status, #updated_at = :updated_at",
            ConditionExpression="attribute_exists(report_id)",
            ExpressionAttributeNames={
                "#status": "status",
                "#updated_at": "updated_at",
            },
            ExpressionAttributeValues={
                ":status": status_val,
                ":updated_at": now_iso,
            },
            ReturnValues="ALL_NEW",
        )
        return DustReport.from_dynamo_item(response["Attributes"])
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ConditionalCheckFailedException":
            raise ReportNotFoundError(f"Report '{report_id}' does not exist") from exc
        raise DynamoDBServiceError(
            f"Failed to update status for report '{report_id}': {exc}"
        ) from exc
    except BotoCoreError as exc:
        raise DynamoDBServiceError(
            f"Failed to update status for report '{report_id}': {exc}"
        ) from exc


def delete_report(report_id: str) -> bool:
    """
    Delete a report item by its report_id.
    """
    table = _get_reports_table()
    try:
        table.delete_item(Key={"report_id": report_id})
        logger.info("dynamodb_service: deleted report '%s'", report_id)
        return True
    except (ClientError, BotoCoreError) as exc:
        raise DynamoDBServiceError(
            f"Failed to delete report '{report_id}': {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Queries & Search
# ---------------------------------------------------------------------------

def list_reports(
    limit: int = 50,
    status: Optional[ReportStatus] = None,
) -> list[DustReport]:
    """
    List reports, optionally filtered by status, ordered newest first.

    Parameters
    ----------
    limit : int
        Maximum number of reports to return (default: 50).
    status : Optional[ReportStatus]
        Optional status filter.
    """
    # ── Mock mode ────────────────────────────────────────────────────────
    if _is_mock():
        results = list(_MOCK_REPORTS.values())
        if status is not None:
            results = [r for r in results if r.status == status]
        results.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return results[:limit]

    table = _get_reports_table()
    scan_kwargs: dict[str, Any] = {}

    if status is not None:
        status_val = status.value if isinstance(status, ReportStatus) else str(status)
        scan_kwargs["FilterExpression"] = Attr("status").eq(status_val)

    try:
        items: list[dict] = []
        done = False
        start_key = None

        while not done and len(items) < limit:
            if start_key:
                scan_kwargs["ExclusiveStartKey"] = start_key
            resp = table.scan(**scan_kwargs)
            items.extend(resp.get("Items", []))
            start_key = resp.get("LastEvaluatedKey")
            done = start_key is None or len(items) >= limit

        reports = [_attach_fresh_image_url(DustReport.from_dynamo_item(it)) for it in items[:limit]]
        reports.sort(key=lambda r: r.created_at, reverse=True)
        return reports
    except (ClientError, BotoCoreError) as exc:
        raise DynamoDBServiceError(f"Failed to list reports: {exc}") from exc


def get_reports_by_case(case_id: str) -> list[DustReport]:
    """
    Retrieve all reports linked to an IncidentCase using GSI 'case_id-index'.
    """
    table = _get_reports_table()
    try:
        resp = table.query(
            IndexName="case_id-index",
            KeyConditionExpression=Key("case_id").eq(case_id),
        )
        items = resp.get("Items", [])
        reports = [_attach_fresh_image_url(DustReport.from_dynamo_item(it)) for it in items]
        reports.sort(key=lambda r: r.created_at, reverse=False)
        return reports
    except (ClientError, BotoCoreError) as exc:
        raise DynamoDBServiceError(
            f"Failed to query reports for case '{case_id}': {exc}"
        ) from exc


def find_nearby_reports(
    latitude: float,
    longitude: float,
    radius_km: Optional[float] = None,
    time_window_days: Optional[int] = None,
    exclude_report_id: Optional[str] = None,
    limit: int = 20,
) -> list[DustReport]:
    """
    Find existing reports within a radius (km) and optional time window.

    Implementation Note
    -------------------
    DynamoDB does not offer native geospatial bounding-box indexes. For MVP
    and hackathon scales, this performs a Scan followed by bounding-box and
    exact Haversine distance filtering in Python.

    Parameters
    ----------
    latitude : float
        Target center latitude.
    longitude : float
        Target center longitude.
    radius_km : Optional[float]
        Radius in kilometers. If None, uses settings.GEO_NEARBY_RADIUS_KM.
    time_window_days : Optional[int]
        Number of past days to include. If None, uses settings.GEO_NEARBY_TIME_WINDOW_DAYS.
    exclude_report_id : Optional[str]
        If provided, omits this specific report from the results (e.g. self-linking).
    limit : int
        Maximum number of nearby reports to return.

    Returns
    -------
    list[DustReport]
        Matching reports sorted from nearest to farthest.
    """
    settings = get_settings()
    rad = radius_km if radius_km is not None else settings.GEO_NEARBY_RADIUS_KM
    days = (
        time_window_days
        if time_window_days is not None
        else settings.GEO_NEARBY_TIME_WINDOW_DAYS
    )

    min_lat, max_lat, min_lon, max_lon = get_bounding_box(latitude, longitude, rad)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days) if days and days > 0 else None

    # ── Mock mode: run geo-search on in-memory store ─────────────────────
    if _is_mock():
        candidates: list[tuple[DustReport, float]] = []
        for report in _MOCK_REPORTS.values():
            if exclude_report_id and report.report_id == exclude_report_id:
                continue
            if cutoff and report.created_at and report.created_at < cutoff:
                continue
            if not (min_lat <= report.latitude <= max_lat and min_lon <= report.longitude <= max_lon):
                continue
            dist = haversine_distance_km(latitude, longitude, report.latitude, report.longitude)
            if dist <= rad:
                candidates.append((report, dist))
        candidates.sort(key=lambda pair: pair[1])
        return [pair[0] for pair in candidates[:limit]]

    table = _get_reports_table()

    try:
        # Scan all items
        items: list[dict] = []
        done = False
        start_key = None

        while not done:
            scan_kwargs: dict[str, Any] = {}
            if start_key:
                scan_kwargs["ExclusiveStartKey"] = start_key
            resp = table.scan(**scan_kwargs)
            items.extend(resp.get("Items", []))
            start_key = resp.get("LastEvaluatedKey")
            done = start_key is None

        candidates: list[tuple[DustReport, float]] = []

        for it in items:
            rid = it.get("report_id")
            if exclude_report_id and rid == exclude_report_id:
                continue

            try:
                report = DustReport.from_dynamo_item(it)
            except Exception as err:
                logger.warning(
                    "dynamodb_service: skipping unparseable item '%s': %s",
                    rid,
                    err,
                )
                continue

            # Time window filter
            if cutoff and report.created_at < cutoff:
                continue

            # Bounding box filter
            if not (min_lat <= report.latitude <= max_lat and min_lon <= report.longitude <= max_lon):
                continue

            # Exact Haversine distance
            dist = haversine_distance_km(latitude, longitude, report.latitude, report.longitude)
            if dist <= rad:
                candidates.append((report, dist))

        # Sort nearest first
        candidates.sort(key=lambda pair: pair[1])
        return [_attach_fresh_image_url(pair[0]) for pair in candidates[:limit]]

    except (ClientError, BotoCoreError) as exc:
        raise DynamoDBServiceError(f"Failed to find nearby reports: {exc}") from exc


# ---------------------------------------------------------------------------
# Audit Events (AuditEvents Table)
# ---------------------------------------------------------------------------

def record_audit_event(
    event_type: str,
    case_id: Optional[str] = None,
    report_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    details: Optional[dict] = None,
    event_id: Optional[str] = None,
) -> dict:
    # ── Mock mode: silently no-op ───────────────────────────────────────────────
    if _is_mock():
        logger.info("dynamodb_service [MOCK]: audit event '%s' logged (no-op)", event_type)
        return {"event_type": event_type, "mock": True}
    """
    Append an audit entry to the AuditEvents DynamoDB table.

    Table schema:
      - PK: event_id (S)
      - SK: timestamp (S)
      - GSI: case_id-timestamp-index
    """
    table = _get_audit_table()
    now_iso = datetime.now(timezone.utc).isoformat()
    eid = event_id or str(uuid.uuid4())

    item: dict[str, Any] = {
        "event_id": eid,
        "timestamp": now_iso,
        "event_type": event_type,
        "actor_id": actor_id or "system",
        "details": json.dumps(details or {}),
    }
    if case_id:
        item["case_id"] = case_id
    if report_id:
        item["report_id"] = report_id

    try:
        table.put_item(Item=item)
        logger.info(
            "dynamodb_service: recorded audit event '%s' (type=%s, case=%s)",
            eid,
            event_type,
            case_id,
        )
        return item
    except (ClientError, BotoCoreError) as exc:
        raise DynamoDBServiceError(f"Failed to record audit event: {exc}") from exc


def get_audit_events_for_case(case_id: str) -> list[dict]:
    """
    Retrieve chronological audit events for a given case using GSI 'case_id-timestamp-index'.
    """
    table = _get_audit_table()
    try:
        resp = table.query(
            IndexName="case_id-timestamp-index",
            KeyConditionExpression=Key("case_id").eq(case_id),
            ScanIndexForward=True,  # ascending / chronological order
        )
        items = resp.get("Items", [])
        for it in items:
            if isinstance(it.get("details"), str):
                try:
                    it["details"] = json.loads(it["details"])
                except Exception:
                    pass
        return items
    except (ClientError, BotoCoreError) as exc:
        raise DynamoDBServiceError(
            f"Failed to query audit events for case '{case_id}': {exc}"
        ) from exc
