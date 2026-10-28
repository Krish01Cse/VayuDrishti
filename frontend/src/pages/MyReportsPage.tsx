import React, { useCallback, useEffect, useState } from 'react';
import {
  FileText,
  MapPin,
  Calendar,
  RefreshCw,
  PlusCircle,
  ChevronRight,
  Brain,
  Zap,
  AlertCircle,
  Clock,
  CheckCircle2,
  Link2,
  XCircle,
  Lightbulb,
  Info,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { listReports, getReport } from '../services/api';
import type { DustReportResponse } from '../types/report';
import { useReportForm } from '../context/ReportFormContext';

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

function priorityClass(score: number): 'high' | 'medium' | 'low' {
  if (score > 70) return 'high';
  if (score >= 40) return 'medium';
  return 'low';
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function truncateId(id: string): string {
  if (id.length <= 20) return id;
  return `${id.slice(0, 8)}…${id.slice(-8)}`;
}

// --------------------------------------------------------------------------
// Sub-components
// --------------------------------------------------------------------------

const StatusIcon: React.FC<{ status: string }> = ({ status }) => {
  switch (status) {
    case 'pending': return <Clock size={11} />;
    case 'analysed': return <CheckCircle2 size={11} />;
    case 'linked': return <Link2 size={11} />;
    case 'closed': return <XCircle size={11} />;
    default: return null;
  }
};

const SkeletonCards: React.FC = () => (
  <>
    {[1, 2, 3, 4, 5].map((i) => (
      <div key={i} className="skeleton-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
          <div className="skeleton-line" style={{ height: '14px', width: '55%' }} />
          <div className="skeleton-line" style={{ height: '20px', width: '72px', borderRadius: '999px' }} />
        </div>
        <div className="skeleton-line" style={{ height: '12px', width: '70%' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <div className="skeleton-line" style={{ height: '5px', flex: 1 }} />
          <div className="skeleton-line" style={{ height: '12px', width: '40px' }} />
        </div>
      </div>
    ))}
  </>
);

// --------------------------------------------------------------------------
// AI Analysis Detail
// --------------------------------------------------------------------------

const AIAnalysisSection: React.FC<{ report: DustReportResponse }> = ({ report }) => {
  const { analysis, status } = report;

  if (!analysis || analysis.analysis_failed) {
    return (
      <div className="analysis-pending-state">
        <div className="analysis-pending-icon">
          <Clock size={32} />
        </div>
        <div style={{ fontWeight: 700 }}>
          {status === 'pending'
            ? 'Vision AI Analysis In Progress'
            : 'Analysis Unavailable'}
        </div>
        <div className="analysis-pending-text">
          {status === 'pending'
            ? 'The Bedrock Vision AI pipeline is currently processing this incident image. Check back shortly.'
            : 'The AI pipeline could not complete analysis for this report. Manual review may be required.'}
        </div>
      </div>
    );
  }

  const confidencePct = Math.round(analysis.confidence * 100);

  return (
    <div className="ai-analysis-card">
      <div className="ai-badge">
        <Brain size={11} />
        <span>Bedrock Vision AI Analysis</span>
      </div>

      <div className="ai-field-grid">
        <div className="ai-field">
          <div className="ai-field-key">Dust Detected</div>
          <div className={`ai-field-val detected-${analysis.dust_detected}`}>
            {analysis.dust_detected ? '✓ Yes — Dust Present' : '✗ No Dust Detected'}
          </div>
        </div>

        <div className="ai-field">
          <div className="ai-field-key">Severity</div>
          <div className="ai-field-val">
            <span className={`severity-chip ${analysis.severity}`}>
              {analysis.severity.toUpperCase()}
            </span>
          </div>
        </div>

        <div className="ai-field">
          <div className="ai-field-key">Source Category</div>
          <div className="ai-field-val" style={{ textTransform: 'capitalize' }}>
            {analysis.dust_category.replace(/_/g, ' ')}
          </div>
        </div>

        <div className="ai-field">
          <div className="ai-field-key">Model Confidence</div>
          <div className="ai-field-val">{confidencePct}%</div>
        </div>
      </div>

      <div className="confidence-bar-wrapper">
        <div className="confidence-label">
          <span>AI Confidence Score</span>
          <span style={{ fontWeight: 700 }}>{confidencePct}%</span>
        </div>
        <div className="confidence-bar">
          <div
            className="confidence-bar-fill"
            style={{ width: `${confidencePct}%` }}
          />
        </div>
      </div>

      {analysis.description && (
        <div style={{ marginTop: '1rem' }}>
          <div className="detail-section-title">
            <Info size={12} />
            AI Scene Description
          </div>
          <div className="ai-description-box">{analysis.description}</div>
        </div>
      )}

      {analysis.suggested_action && (
        <div className="ai-action-box">
          <Lightbulb size={16} style={{ flexShrink: 0, marginTop: '1px' }} />
          <span>{analysis.suggested_action}</span>
        </div>
      )}
    </div>
  );
};

// --------------------------------------------------------------------------
// Detail Panel
// --------------------------------------------------------------------------

const DetailPanel: React.FC<{
  selectedId: string | null;
  detail: DustReportResponse | null;
  loadingDetail: boolean;
  detailError: string | null;
}> = ({ selectedId, detail, loadingDetail, detailError }) => {
  if (!selectedId) {
    return (
      <div className="glass-panel detail-panel">
        <div className="detail-panel-inner">
          <div className="detail-panel-header">
            <div className="detail-panel-title">
              <Zap size={18} color="var(--cyan-400)" />
              Report Details
            </div>
          </div>
          <div className="empty-state">
            <div className="empty-state-icon">
              <ChevronRight size={28} />
            </div>
            <div className="empty-state-title">Select a Report</div>
            <div className="empty-state-sub">
              Click any card on the left to view the full incident detail and AI analysis.
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (loadingDetail) {
    return (
      <div className="glass-panel detail-panel">
        <div className="detail-panel-inner">
          <div className="detail-panel-header">
            <div className="detail-panel-title">
              <Zap size={18} color="var(--cyan-400)" />
              Loading…
            </div>
          </div>
          <div className="detail-panel-body">
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {[80, 55, 100, 70, 90, 40].map((w, i) => (
                <div key={i} className="skeleton-line" style={{ height: '14px', width: `${w}%` }} />
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (detailError || !detail) {
    return (
      <div className="glass-panel detail-panel">
        <div className="detail-panel-inner">
          <div className="detail-panel-header">
            <div className="detail-panel-title">
              <Zap size={18} color="var(--cyan-400)" />
              Report Details
            </div>
          </div>
          <div className="empty-state">
            <div className="empty-state-icon" style={{ background: 'rgba(244,63,94,0.12)', color: 'var(--rose-500)' }}>
              <AlertCircle size={28} />
            </div>
            <div className="empty-state-title">Failed to Load</div>
            <div className="empty-state-sub">{detailError || 'Could not retrieve report details.'}</div>
          </div>
        </div>
      </div>
    );
  }

  const pClass = priorityClass(detail.priority_score);

  return (
    <div className="glass-panel detail-panel">
      <div className="detail-panel-inner">
        <div className="detail-panel-header">
          <div className="detail-panel-title">
            <Zap size={18} color="var(--cyan-400)" />
            Report Detail
          </div>
          <span className={`status-badge ${detail.status}`}>
            <StatusIcon status={detail.status} />
            <span>{detail.status}</span>
          </span>
        </div>

        <div className="detail-panel-body">
          {/* Image */}
          {detail.image_url && (
            <div>
              <div className="detail-section-title">
                Evidence Photo
              </div>
              <a href={detail.image_url} target="_blank" rel="noreferrer">
                <img
                  src={detail.image_url}
                  alt="Incident evidence"
                  className="detail-image"
                />
              </a>
            </div>
          )}

          {/* Core Info Grid */}
          <div>
            <div className="detail-section-title">Location & Metadata</div>
            <div className="info-grid">
              <div className="info-tile" style={{ gridColumn: '1 / -1' }}>
                <div className="info-tile-label">Report ID</div>
                <div className="info-tile-value mono">{detail.report_id}</div>
              </div>

              <div className="info-tile">
                <div className="info-tile-label">Latitude</div>
                <div className="info-tile-value mono">{detail.latitude.toFixed(5)}° N</div>
              </div>

              <div className="info-tile">
                <div className="info-tile-label">Longitude</div>
                <div className="info-tile-value mono">{detail.longitude.toFixed(5)}° E</div>
              </div>

              {detail.address && (
                <div className="info-tile" style={{ gridColumn: '1 / -1' }}>
                  <div className="info-tile-label">Address</div>
                  <div className="info-tile-value">{detail.address}</div>
                </div>
              )}

              <div className="info-tile">
                <div className="info-tile-label">Submitted</div>
                <div className="info-tile-value">{formatDate(detail.created_at)}</div>
              </div>

              <div className="info-tile">
                <div className="info-tile-label">Last Updated</div>
                <div className="info-tile-value">{formatDate(detail.updated_at)}</div>
              </div>
            </div>
          </div>

          {/* Priority Score */}
          <div>
            <div className="detail-section-title">Priority Score</div>
            <div className="priority-meter" style={{ marginTop: '0.25rem' }}>
              <div className="priority-meter-bar">
                <div
                  className={`priority-meter-fill ${pClass}`}
                  style={{ width: `${detail.priority_score}%` }}
                />
              </div>
              <span className={`priority-score-label ${pClass}`}>
                {detail.priority_score.toFixed(1)}
              </span>
            </div>
          </div>

          {/* Resident Description */}
          {detail.description && (
            <div>
              <div className="detail-section-title">Resident's Description</div>
              <div
                style={{
                  background: 'rgba(10,15,28,0.6)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '0.85rem',
                  fontSize: '0.85rem',
                  color: 'var(--text-secondary)',
                  lineHeight: '1.65',
                }}
              >
                {detail.description}
              </div>
            </div>
          )}

          {/* AI Analysis */}
          <div>
            <div className="detail-section-title">
              <Brain size={12} />
              AI Vision Analysis
            </div>
            <AIAnalysisSection report={detail} />
          </div>
        </div>
      </div>
    </div>
  );
};

// --------------------------------------------------------------------------
// Main Page
// --------------------------------------------------------------------------

export const MyReportsPage: React.FC = () => {
  const { selectedReportIdInList, setSelectedReportIdInList } = useReportForm();
  const selectedId = selectedReportIdInList;
  const [reports, setReports] = useState<DustReportResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [detail, setDetail] = useState<DustReportResponse | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Fetch report list
  const fetchReports = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listReports(20);
      // sort newest first
      data.sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      );
      setReports(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load reports.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchReports();
  }, [fetchReports]);

  // Load detail for selected report (including restored selection)
  useEffect(() => {
    if (selectedReportIdInList && !detail) {
      setLoadingDetail(true);
      getReport(selectedReportIdInList)
        .then((data) => setDetail(data))
        .catch((err) => setDetailError(err instanceof Error ? err.message : 'Failed to load report detail.'))
        .finally(() => setLoadingDetail(false));
    }
  }, [selectedReportIdInList]);

  // Fetch detail when a card is selected
  const handleSelectCard = async (id: string) => {
    if (id === selectedReportIdInList) return;
    setSelectedReportIdInList(id);
    setDetail(null);
    setDetailError(null);
    setLoadingDetail(true);
    try {
      const data = await getReport(id);
      setDetail(data);
    } catch (err: unknown) {
      setDetailError(err instanceof Error ? err.message : 'Failed to load report detail.');
    } finally {
      setLoadingDetail(false);
    }
  };

  return (
    <div>
      {/* Page Header */}
      <div className="page-header">
        <div className="page-badge">
          <FileText size={13} />
          <span>Incident Dashboard</span>
        </div>
        <h1 className="page-title">My Reports</h1>
        <p className="page-subtitle">
          Browse submitted dust-pollution incidents, their AI vision analysis results,
          priority scores, and current lifecycle status.
        </p>
      </div>

      <div className="reports-page-grid">
        {/* Left — Report List */}
        <div className="glass-panel reports-list-panel">
          <div className="reports-list-header">
            <div className="reports-list-header-title">
              <FileText size={18} color="var(--indigo-500)" />
              <span>Submitted Incidents</span>
              {!loading && !error && (
                <span className="reports-count-pill">{reports.length}</span>
              )}
            </div>
            <button
              type="button"
              className="btn-icon"
              onClick={fetchReports}
              disabled={loading}
              title="Refresh list"
            >
              <RefreshCw size={15} className={loading ? 'spinning' : ''} />
            </button>
          </div>

          <div className="reports-list-body">
            {loading ? (
              <SkeletonCards />
            ) : error ? (
              <div className="empty-state">
                <div
                  className="empty-state-icon"
                  style={{ background: 'rgba(244,63,94,0.12)', color: 'var(--rose-500)' }}
                >
                  <AlertCircle size={28} />
                </div>
                <div className="empty-state-title">Could Not Load Reports</div>
                <div className="empty-state-sub">{error}</div>
                <button type="button" className="btn-secondary" onClick={fetchReports}>
                  <RefreshCw size={14} />
                  <span>Retry</span>
                </button>
              </div>
            ) : reports.length === 0 ? (
              <div className="empty-state">
                <div className="empty-state-icon">
                  <FileText size={28} />
                </div>
                <div className="empty-state-title">No Reports Yet</div>
                <div className="empty-state-sub">
                  Submit your first dust-pollution incident to see it here.
                </div>
                <Link to="/submit" className="btn-primary" style={{ width: 'auto' }}>
                  <PlusCircle size={16} />
                  <span>Submit a Report</span>
                </Link>
              </div>
            ) : (
              reports.map((report) => {
                const pClass = priorityClass(report.priority_score);
                const isSelected = selectedId === report.report_id;
                return (
                  <div
                    key={report.report_id}
                    className={`report-card ${isSelected ? 'selected' : ''}`}
                    onClick={() => handleSelectCard(report.report_id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) =>
                      e.key === 'Enter' && handleSelectCard(report.report_id)
                    }
                    aria-label={`View report ${report.report_id}`}
                  >
                    <div className="report-card-top">
                      <span className="report-card-id" title={report.report_id}>
                        {truncateId(report.report_id)}
                      </span>
                      <span className={`status-badge ${report.status}`}>
                        <StatusIcon status={report.status} />
                        <span>{report.status}</span>
                      </span>
                    </div>

                    <div className="report-card-meta">
                      <span className="report-card-location">
                        <MapPin size={12} />
                        {report.address
                          ? report.address.slice(0, 38) + (report.address.length > 38 ? '…' : '')
                          : `${report.latitude.toFixed(4)}° N, ${report.longitude.toFixed(4)}° E`}
                      </span>
                      <span className="report-card-date">
                        <Calendar size={11} style={{ display: 'inline', marginRight: '3px' }} />
                        {formatDate(report.created_at)}
                      </span>
                    </div>

                    {/* Priority Meter */}
                    <div className="priority-meter">
                      <div className="priority-meter-bar">
                        <div
                          className={`priority-meter-fill ${pClass}`}
                          style={{ width: `${report.priority_score}%` }}
                        />
                      </div>
                      <span className={`priority-score-label ${pClass}`}>
                        {report.priority_score.toFixed(1)}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right — Detail Panel */}
        <div className="detail-panel">
          <DetailPanel
            selectedId={selectedId}
            detail={detail}
            loadingDetail={loadingDetail}
            detailError={detailError}
          />
        </div>
      </div>
    </div>
  );
};
