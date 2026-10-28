# -*- coding: utf-8 -*-
"""
models/report.py — Pydantic models for VayuDrishti

Covers:
  - DustReportCreate   : what the client POSTs (multipart form fields)
  - VisualAnalysis     : structured output from the vision AI
  - DustReport         : the full record stored in DynamoDB
  - ReportStatus       : allowed lifecycle states
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ReportStatus(str, Enum):
    """Lifecycle states for a dust-pollution report."""
    PENDING   = "pending"    # just submitted, analysis not yet done
    ANALYSED  = "analysed"   # vision AI has returned a result
    LINKED    = "linked"     # attached to an IncidentCase
    CLOSED    = "closed"     # case resolved / rejected


class DustCategory(str, Enum):
    """Dust-source categories that the vision model may identify."""
    CONSTRUCTION       = "construction"
    ROAD_DUST          = "road_dust"
    INDUSTRIAL         = "industrial"
    VEHICLE_EMISSIONS  = "vehicle_emissions"
    OPEN_BURNING       = "open_burning"
    UNKNOWN            = "unknown"


class SeverityLevel(str, Enum):
    """How bad the pollution looks in the image."""
    LOW      = "low"
    MODERATE = "moderate"
    HIGH     = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class LocationCreate(BaseModel):
    """GPS coordinates submitted with a report."""
    latitude:  float = Field(..., ge=-90,  le=90,  description="Latitude in decimal degrees")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude in decimal degrees")
    address:   Optional[str] = Field(None, max_length=500, description="Human-readable address (optional)")


class VisualAnalysis(BaseModel):
    """
    Structured output from the vision AI (Bedrock / OpenAI / mock).

    The vision_service must always return a valid instance of this model.
    If parsing fails, use VisualAnalysis.failed() to return a safe default.
    """
    dust_detected:       bool         = Field(...,  description="True if dust / pollution is visible")
    dust_category:       DustCategory = Field(...,  description="Best-match source category")
    severity:            SeverityLevel = Field(..., description="Estimated severity level")
    confidence:          float        = Field(...,  ge=0.0, le=1.0, description="Model confidence 0–1")
    description:         str          = Field(...,  max_length=1000, description="Free-text description from the model")
    suggested_action:    str          = Field(...,  max_length=500,  description="Recommended follow-up action")
    analysis_failed:     bool         = Field(False, description="True when vision call failed; fields above are defaults")

    @classmethod
    def failed(cls) -> "VisualAnalysis":
        """Return a safe placeholder when the vision service errors out."""
        return cls(
            dust_detected=False,
            dust_category=DustCategory.UNKNOWN,
            severity=SeverityLevel.LOW,
            confidence=0.0,
            description="Vision analysis could not be completed.",
            suggested_action="Manual review required.",
            analysis_failed=True,
        )


# ---------------------------------------------------------------------------
# Request models (what the client sends)
# ---------------------------------------------------------------------------

class DustReportCreate(BaseModel):
    """
    Fields the client POSTs when submitting a new report.
    The image file itself is handled as a separate multipart upload.
    """
    latitude:    float         = Field(..., ge=-90,  le=90)
    longitude:   float         = Field(..., ge=-180, le=180)
    address:     Optional[str] = Field(None, max_length=500)
    description: Optional[str] = Field(None, max_length=2000,
                                        description="Resident's own description of the issue")
    category:    Optional[str] = Field(None, max_length=100,
                                        description="Resident-selected source category")

    @field_validator("description", mode="before")
    @classmethod
    def strip_description(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v


# ---------------------------------------------------------------------------
# Full DB record model
# ---------------------------------------------------------------------------

class DustReport(BaseModel):
    """
    Complete report record as stored in DynamoDB (DustReports table).
    Created by the backend; never sent directly by the client.
    """
    # --- Identity ---
    report_id:   str = Field(default_factory=lambda: str(uuid.uuid4()))
    case_id:     Optional[str] = Field(None, description="Set when report is linked to an IncidentCase")

    # --- Location ---
    latitude:    float
    longitude:   float
    address:     Optional[str] = None

    # --- Resident input ---
    description: Optional[str] = None

    # --- Image storage ---
    s3_key:         Optional[str] = Field(None, description="S3 object key for the uploaded image")
    s3_bucket:      Optional[str] = Field(None, description="S3 bucket name")
    image_url:      Optional[str] = Field(None, description="Pre-signed URL (short-lived, for display)")

    # --- AI analysis ---
    analysis:        Optional[VisualAnalysis] = None
    priority_score:  float = Field(0.0, ge=0.0, le=100.0,
                                   description="Computed priority 0–100 (higher = more urgent)")

    # --- Lifecycle ---
    status:      ReportStatus = Field(default=ReportStatus.PENDING)
    created_at:  datetime     = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at:  datetime     = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def compute_priority(self) -> float:
        """
        Simple deterministic priority score (0–100).

        Formula:
          base score from severity  (critical=80, high=60, moderate=40, low=20)
          + confidence bonus        (up to 15 pts)
          + dust_detected bonus     (5 pts)

        Always safe to call — returns 0 if analysis is missing.
        """
        if self.analysis is None or self.analysis.analysis_failed:
            return 0.0

        severity_map = {
            SeverityLevel.CRITICAL: 80.0,
            SeverityLevel.HIGH:     60.0,
            SeverityLevel.MODERATE: 40.0,
            SeverityLevel.LOW:      20.0,
        }
        base       = severity_map.get(self.analysis.severity, 0.0)
        confidence = self.analysis.confidence * 15.0
        detected   = 5.0 if self.analysis.dust_detected else 0.0

        return min(round(base + confidence + detected, 2), 100.0)

    def to_dynamo_item(self) -> dict:
        """
        Serialize to a flat dict suitable for DynamoDB put_item.
        Nested VisualAnalysis is stored as a JSON string.
        """
        import json

        item: dict = {
            "report_id":      self.report_id,
            "latitude":       str(self.latitude),
            "longitude":      str(self.longitude),
            "status":         self.status.value,
            "priority_score": str(self.priority_score),
            "created_at":     self.created_at.isoformat(),
            "updated_at":     self.updated_at.isoformat(),
        }

        # Optional fields — only include when set
        if self.case_id:
            item["case_id"] = self.case_id
        if self.address:
            item["address"] = self.address
        if self.description:
            item["description"] = self.description
        if self.s3_key:
            item["s3_key"] = self.s3_key
        if self.s3_bucket:
            item["s3_bucket"] = self.s3_bucket
        if self.image_url:
            item["image_url"] = self.image_url
        if self.analysis:
            item["analysis"] = self.analysis.model_dump_json()

        return item

    @classmethod
    def from_dynamo_item(cls, item: dict) -> "DustReport":
        """Deserialize a DynamoDB item back into a DustReport."""
        import json

        analysis: Optional[VisualAnalysis] = None
        if raw := item.get("analysis"):
            try:
                analysis = VisualAnalysis.model_validate_json(raw)
            except Exception:
                analysis = VisualAnalysis.failed()

        return cls(
            report_id      = item["report_id"],
            case_id        = item.get("case_id"),
            latitude       = float(item["latitude"]),
            longitude      = float(item["longitude"]),
            address        = item.get("address"),
            description    = item.get("description"),
            s3_key         = item.get("s3_key"),
            s3_bucket      = item.get("s3_bucket"),
            image_url      = item.get("image_url"),
            analysis       = analysis,
            priority_score = float(item.get("priority_score", 0.0)),
            status         = ReportStatus(item.get("status", ReportStatus.PENDING.value)),
            created_at     = datetime.fromisoformat(item["created_at"]),
            updated_at     = datetime.fromisoformat(item["updated_at"]),
        )


# ---------------------------------------------------------------------------
# Response models (what the API returns to the client)
# ---------------------------------------------------------------------------

class DustReportResponse(BaseModel):
    """API response shape — safe subset of DustReport for the client."""
    report_id:      str
    case_id:        Optional[str]          = None
    latitude:       float
    longitude:      float
    address:        Optional[str]          = None
    description:    Optional[str]          = None
    image_url:      Optional[str]          = None
    analysis:       Optional[VisualAnalysis] = None
    priority_score: float
    status:         ReportStatus
    created_at:     datetime
    updated_at:     datetime

    @classmethod
    def from_report(cls, report: DustReport) -> "DustReportResponse":
        """Build response from an internal DustReport."""
        return cls(
            report_id      = report.report_id,
            case_id        = report.case_id,
            latitude       = report.latitude,
            longitude      = report.longitude,
            address        = report.address,
            description    = report.description,
            image_url      = report.image_url,
            analysis       = report.analysis,
            priority_score = report.priority_score,
            status         = report.status,
            created_at     = report.created_at,
            updated_at     = report.updated_at,
        )
