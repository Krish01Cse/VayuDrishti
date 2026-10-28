import type { DustReportResponse, SubmitReportFormData } from '../types/report';

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(message: string, status: number, data?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

/**
 * Submit a new dust-pollution report with image and metadata as multipart/form-data.
 */
export async function submitReport(
  formData: SubmitReportFormData
): Promise<DustReportResponse> {
  if (!formData.image) {
    throw new Error('Please select an image to upload.');
  }
  if (formData.latitude === '' || formData.longitude === '') {
    throw new Error('Please choose GPS coordinates on the map.');
  }

  const payload = new FormData();
  payload.append('image', formData.image, formData.image.name);
  payload.append('latitude', formData.latitude.toString());
  payload.append('longitude', formData.longitude.toString());

  if (formData.address.trim()) {
    payload.append('address', formData.address.trim());
  }

  // Build clean description incorporating resident input and category
  let combinedDescription = formData.description.trim();
  if (formData.category && formData.category !== 'unknown') {
    const categoryTag = `[Category: ${formData.category}]`;
    combinedDescription = combinedDescription
      ? `${categoryTag} ${combinedDescription}`
      : categoryTag;
  }

  if (combinedDescription) {
    payload.append('description', combinedDescription);
  }

  // Also include category in form data
  payload.append('category', formData.category);

  const response = await fetch(`${API_BASE_URL}/reports`, {
    method: 'POST',
    body: payload,
  });

  if (!response.ok) {
    let errorDetail = `Submission failed (${response.status} ${response.statusText})`;
    try {
      const errJson = await response.json();
      if (errJson && errJson.detail) {
        if (typeof errJson.detail === 'string') {
          errorDetail = errJson.detail;
        } else if (Array.isArray(errJson.detail)) {
          errorDetail = errJson.detail.map((e: { msg?: string }) => e.msg || JSON.stringify(e)).join(', ');
        }
      }
    } catch {
      // Use fallback error message
    }
    throw new ApiError(errorDetail, response.status);
  }

  return response.json();
}

/**
 * Fetch a single report by ID.
 */
export async function getReport(reportId: string): Promise<DustReportResponse> {
  const response = await fetch(`${API_BASE_URL}/reports/${encodeURIComponent(reportId)}`);
  if (!response.ok) {
    throw new ApiError(`Failed to fetch report ${reportId}`, response.status);
  }
  return response.json();
}

/**
 * Fetch reports list with optional status and limit.
 */
export async function listReports(limit = 20, status?: string): Promise<DustReportResponse[]> {
  const url = new URL(`${API_BASE_URL}/reports`);
  url.searchParams.set('limit', limit.toString());
  if (status) {
    url.searchParams.set('status', status);
  }
  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new ApiError('Failed to fetch reports list', response.status);
  }
  return response.json();
}

/**
 * Check backend API health and connectivity status.
 */
export async function checkApiHealth(detailed = false): Promise<{
  status: string;
  version?: string;
  region?: string;
  storage_provider?: string;
  vision_provider?: string;
}> {
  try {
    const res = await fetch(`${API_BASE_URL.replace(/\/api\/v1\/?$/, '')}/health${detailed ? '?detailed=true' : ''}`);
    if (res.ok) {
      return await res.json();
    }
  } catch {
    // try fallback route
  }
  try {
    const res2 = await fetch(`${API_BASE_URL}/health${detailed ? '?detailed=true' : ''}`);
    if (res2.ok) {
      return await res2.json();
    }
  } catch (err) {
    return { status: 'offline' };
  }
  return { status: 'offline' };
}
