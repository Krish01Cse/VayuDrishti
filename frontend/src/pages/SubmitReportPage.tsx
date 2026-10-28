import React, { useState, useRef } from 'react';
import {
  UploadCloud,
  X,
  Send,
  CheckCircle2,
  AlertTriangle,
  Copy,
  ExternalLink,
  RotateCcw,
  HardHat,
  Hammer,
  Truck,
  HelpCircle,
  Clock,
  Sparkles,
} from 'lucide-react';
import { MapPicker } from '../components/MapPicker';
import { submitReport, ApiError } from '../services/api';
import type { DustCategory } from '../types/report';
import { useReportForm } from '../context/ReportFormContext';

const CATEGORY_OPTIONS: {
  value: DustCategory;
  label: string;
  desc: string;
  icon: React.ReactNode;
}[] = [
  {
    value: 'construction',
    label: 'Construction',
    desc: 'Excavation, unpaved building dust',
    icon: <HardHat size={18} />,
  },
  {
    value: 'demolition',
    label: 'Demolition',
    desc: 'Building breakdown, debris clouds',
    icon: <Hammer size={18} />,
  },
  {
    value: 'road_dust',
    label: 'Road Dust',
    desc: 'Unpaved roads, heavy traffic dust',
    icon: <Truck size={18} />,
  },
  {
    value: 'unknown',
    label: 'Unknown / Other',
    desc: 'Unverified pollution source',
    icon: <HelpCircle size={18} />,
  },
];

export const SubmitReportPage: React.FC = () => {
  const {
    formData,
    setFormData,
    imagePreviewUrl,
    setImageFile,
    setImagePreviewUrl,
    submittedReport,
    setSubmittedReport,
    resetDraft,
  } = useReportForm();

  const [isDragging, setIsDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Handle image selection
  const handleFileChange = (file: File | null) => {
    if (!file) return;

    if (!file.type.startsWith('image/')) {
      setErrorMessage('Please select a valid image file (JPEG or PNG).');
      return;
    }

    setImageFile(file);
    setErrorMessage(null);

    const reader = new FileReader();
    reader.onload = () => {
      setImagePreviewUrl(reader.result as string);
    };
    reader.readAsDataURL(file);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileChange(e.dataTransfer.files[0]);
    }
  };

  const handleRemoveImage = (e: React.MouseEvent) => {
    e.stopPropagation();
    setImageFile(null);
    setImagePreviewUrl(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  // Map pin position change handler
  const handlePositionChange = (pos: { lat: number; lng: number }) => {
    setFormData((prev) => ({
      ...prev,
      latitude: pos.lat,
      longitude: pos.lng,
    }));
  };

  // Manual lat/lng input changes
  const handleLatChange = (val: string) => {
    const parsed = val === '' ? '' : parseFloat(val);
    setFormData((prev) => ({ ...prev, latitude: parsed }));
  };

  const handleLngChange = (val: string) => {
    const parsed = val === '' ? '' : parseFloat(val);
    setFormData((prev) => ({ ...prev, longitude: parsed }));
  };

  // Form submission
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    if (!formData.image) {
      setErrorMessage('Please upload a photo of the dust pollution site.');
      return;
    }

    if (formData.latitude === '' || formData.longitude === '') {
      setErrorMessage('Please pick or enter valid GPS coordinates.');
      return;
    }

    try {
      setSubmitting(true);
      const response = await submitReport(formData);
      setSubmittedReport(response);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setErrorMessage(err.message);
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('An unexpected error occurred while submitting your report.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleResetForm = () => {
    resetDraft();
    setErrorMessage(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleCopyId = (id: string) => {
    navigator.clipboard.writeText(id);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  return (
    <div>
      <div className="page-header">
        <div className="page-badge">
          <Sparkles size={13} />
          <span>Real-time Citizen Reporting</span>
        </div>
        <h1 className="page-title">Submit Pollution Incident</h1>
        <p className="page-subtitle">
          Pinpoint fugitive dust emissions, upload site photographs, and trigger our
          multimodal vision AI pipeline to assess severity and coordinate response.
        </p>
      </div>

      {submittedReport ? (
        /* Success Report View */
        <div className="glass-panel success-card">
          <div className="success-badge-icon">
            <CheckCircle2 size={36} strokeWidth={2.5} />
          </div>

          <h2 className="success-title">Report Submitted Successfully</h2>
          <p className="success-subtitle">
            Your incident has been logged into the DynamoDB ledger and sent to the Bedrock
            Vision AI engine for automated analysis.
          </p>

          <div className="report-details-box">
            <div className="detail-row">
              <span className="detail-label">Report ID</span>
              <div className="detail-value mono">
                <span>{submittedReport.report_id}</span>
                <button
                  type="button"
                  className="copy-btn"
                  onClick={() => handleCopyId(submittedReport.report_id)}
                  title="Copy Report ID"
                >
                  <Copy size={12} />
                  <span>{copiedId ? 'Copied!' : 'Copy'}</span>
                </button>
              </div>
            </div>

            <div className="detail-row">
              <span className="detail-label">Processing Status</span>
              <div className="detail-value">
                <span className={`status-badge ${submittedReport.status}`}>
                  <Clock size={12} />
                  <span>{submittedReport.status}</span>
                </span>
              </div>
            </div>

            <div className="detail-row">
              <span className="detail-label">Initial Priority Score</span>
              <div className="detail-value mono">
                {submittedReport.priority_score.toFixed(1)} / 100
              </div>
            </div>

            <div className="detail-row">
              <span className="detail-label">GPS Coordinates</span>
              <div className="detail-value mono">
                {submittedReport.latitude.toFixed(5)}° N, {submittedReport.longitude.toFixed(5)}° E
              </div>
            </div>

            {submittedReport.address && (
              <div className="detail-row">
                <span className="detail-label">Address</span>
                <div className="detail-value">{submittedReport.address}</div>
              </div>
            )}

            {submittedReport.description && (
              <div className="detail-row">
                <span className="detail-label">Description</span>
                <div className="detail-value" style={{ maxWidth: '350px', textAlign: 'right' }}>
                  {submittedReport.description}
                </div>
              </div>
            )}

            {submittedReport.image_url && (
              <div style={{ marginTop: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                  <span className="detail-label">Uploaded Image (Signed S3 URL)</span>
                  <a
                    href={submittedReport.image_url}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.3rem',
                      fontSize: '0.75rem',
                      color: 'var(--cyan-400)',
                    }}
                  >
                    <span>Open full image</span>
                    <ExternalLink size={12} />
                  </a>
                </div>
                <div className="success-image-preview">
                  <img src={submittedReport.image_url} alt="Submitted dust evidence" />
                </div>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: '1rem', justifyContent: 'center' }}>
            <button type="button" className="btn-secondary" onClick={handleResetForm}>
              <RotateCcw size={16} />
              <span>Submit Another Report</span>
            </button>
            <a href="/my-reports" className="btn-primary" style={{ width: 'auto' }}>
              <span>View In Reports List</span>
            </a>
          </div>
        </div>
      ) : (
        /* Report Submission Grid */
        <div className="submit-grid">
          {/* Left Column: Input Form */}
          <form className="glass-panel form-section" onSubmit={handleSubmit}>
            {errorMessage && (
              <div className="alert-error">
                <AlertTriangle size={18} style={{ flexShrink: 0 }} />
                <span>{errorMessage}</span>
              </div>
            )}

            {/* 1. Photo Evidence Upload */}
            <div className="form-group">
              <label className="form-label">
                <span>
                  Photo Evidence <span className="required">*</span>
                </span>
                <span className="hint">JPEG or PNG, max 10MB</span>
              </label>

              {imagePreviewUrl ? (
                <div className="preview-card">
                  <img
                    src={imagePreviewUrl}
                    alt="Upload preview"
                    className="preview-image"
                  />
                  <div className="preview-overlay">
                    <div className="preview-meta">
                      <span className="preview-file-tag">
                        {formData.image?.name || 'Evidence photo'}
                      </span>
                      <button
                        type="button"
                        className="preview-remove-btn"
                        onClick={handleRemoveImage}
                        title="Remove photo"
                      >
                        <X size={16} />
                      </button>
                    </div>
                    <div style={{ fontSize: '0.74rem', color: '#cbd5e1' }}>
                      {formData.image
                        ? `${(formData.image.size / (1024 * 1024)).toFixed(2)} MB`
                        : ''}
                    </div>
                  </div>
                </div>
              ) : (
                <div
                  className={`upload-dropzone ${isDragging ? 'dragging' : ''}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragging(true);
                  }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/jpeg,image/png,image/jpg"
                    onChange={(e) =>
                      e.target.files && handleFileChange(e.target.files[0])
                    }
                  />
                  <div className="upload-icon-circle">
                    <UploadCloud size={24} />
                  </div>
                  <div className="upload-title">Click to upload or drag & drop</div>
                  <div className="upload-subtitle">
                    Clear photos of construction plumes, smoke, or road dust
                  </div>
                </div>
              )}
            </div>

            {/* 2. Dust Source Category */}
            <div className="form-group">
              <label className="form-label">
                <span>Suspected Category</span>
                <span className="hint">Select best match</span>
              </label>
              <div className="category-chips">
                {CATEGORY_OPTIONS.map((cat) => {
                  const isSelected = formData.category === cat.value;
                  return (
                    <button
                      key={cat.value}
                      type="button"
                      className={`category-chip ${isSelected ? 'selected' : ''}`}
                      onClick={() =>
                        setFormData((prev) => ({ ...prev, category: cat.value }))
                      }
                    >
                      <div className="category-chip-icon">{cat.icon}</div>
                      <div className="category-chip-info">
                        <div className="category-chip-title">{cat.label}</div>
                        <div className="category-chip-desc">{cat.desc}</div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* 3. Coordinates (Auto-filled by Map) */}
            <div className="form-group">
              <label className="form-label">
                <span>
                  GPS Coordinates <span className="required">*</span>
                </span>
                <span className="hint">Auto-filled by clicking map</span>
              </label>
              <div className="coords-grid">
                <div className="coord-input-wrapper">
                  <span className="coord-icon">LAT</span>
                  <input
                    type="number"
                    step="0.00001"
                    className="form-control"
                    placeholder="28.6139"
                    value={formData.latitude}
                    onChange={(e) => handleLatChange(e.target.value)}
                    required
                  />
                </div>
                <div className="coord-input-wrapper">
                  <span className="coord-icon">LNG</span>
                  <input
                    type="number"
                    step="0.00001"
                    className="form-control"
                    placeholder="77.2090"
                    value={formData.longitude}
                    onChange={(e) => handleLngChange(e.target.value)}
                    required
                  />
                </div>
              </div>
            </div>

            {/* 4. Human-readable Address */}
            <div className="form-group">
              <label className="form-label">
                <span>Location Address / Landmark</span>
                <span className="hint">Optional</span>
              </label>
              <input
                type="text"
                className="form-control"
                placeholder="e.g. Near Barakhamba Metro Station, Connaught Place"
                value={formData.address}
                maxLength={500}
                onChange={(e) =>
                  setFormData((prev) => ({ ...prev, address: e.target.value }))
                }
              />
            </div>

            {/* 5. Resident Description */}
            <div className="form-group">
              <label className="form-label">
                <span>Resident Description</span>
                <span className="hint">
                  {formData.description.length}/2000 chars
                </span>
              </label>
              <textarea
                className="form-control"
                placeholder="Describe the visible dust density, wind direction, nearby active machinery, or duration..."
                value={formData.description}
                maxLength={2000}
                onChange={(e) =>
                  setFormData((prev) => ({
                    ...prev,
                    description: e.target.value,
                  }))
                }
              />
            </div>

            {/* Submit Action */}
            <button
              type="submit"
              className="btn-primary"
              disabled={submitting}
            >
              {submitting ? (
                <>
                  <div
                    className="spinning"
                    style={{
                      width: '18px',
                      height: '18px',
                      border: '2px solid rgba(255,255,255,0.3)',
                      borderTopColor: '#fff',
                      borderRadius: '50%',
                    }}
                  />
                  <span>Dispatching to S3 & AI Pipeline...</span>
                </>
              ) : (
                <>
                  <Send size={18} />
                  <span>Submit Dust Incident Report</span>
                </>
              )}
            </button>
          </form>

          {/* Right Column: Embedded Leaflet Map */}
          <div>
            <MapPicker
              position={
                formData.latitude !== '' && formData.longitude !== ''
                  ? {
                      lat: Number(formData.latitude),
                      lng: Number(formData.longitude),
                    }
                  : null
              }
              onPositionChange={handlePositionChange}
            />
          </div>
        </div>
      )}
    </div>
  );
};
