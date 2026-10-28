import React, { createContext, useContext, useState, useEffect } from 'react';
import type { DustCategory, DustReportResponse, SubmitReportFormData } from '../types/report';

interface ReportFormContextType {
  formData: SubmitReportFormData;
  setFormData: React.Dispatch<React.SetStateAction<SubmitReportFormData>>;
  updateFormField: <K extends keyof SubmitReportFormData>(field: K, value: SubmitReportFormData[K]) => void;
  imageFile: File | null;
  setImageFile: (file: File | null) => void;
  imagePreviewUrl: string | null;
  setImagePreviewUrl: (url: string | null) => void;
  submittedReport: DustReportResponse | null;
  setSubmittedReport: (report: DustReportResponse | null) => void;
  resetDraft: () => void;
  // Preservation for MyReports page
  selectedReportIdInList: string | null;
  setSelectedReportIdInList: (id: string | null) => void;
  // Preservation for Map page
  mapSelectedReportId: string | null;
  setMapSelectedReportId: (id: string | null) => void;
  mapStatusFilter: string;
  setMapStatusFilter: (status: string) => void;
}

const STORAGE_KEY_FORM = 'vayudrishti_draft_form';
const STORAGE_KEY_IMAGE_PREVIEW = 'vayudrishti_draft_image';
const STORAGE_KEY_SUBMITTED = 'vayudrishti_submitted_report';

const DEFAULT_FORM_DATA: SubmitReportFormData = {
  image: null,
  latitude: 28.6139,
  longitude: 77.2090,
  address: '',
  description: '',
  category: 'construction' as DustCategory,
};

// Helper: convert DataURL to File
function dataUrlToFile(dataUrl: string, filename = 'uploaded-photo.jpg'): File | null {
  try {
    const arr = dataUrl.split(',');
    const mimeMatch = arr[0].match(/:(.*?);/);
    const mime = mimeMatch ? mimeMatch[1] : 'image/jpeg';
    const bstr = atob(arr[1]);
    let n = bstr.length;
    const u8arr = new Uint8Array(n);
    while (n--) {
      u8arr[n] = bstr.charCodeAt(n);
    }
    return new File([u8arr], filename, { type: mime });
  } catch {
    return null;
  }
}

const ReportFormContext = createContext<ReportFormContextType | undefined>(undefined);

export const ReportFormProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Initialize form data from sessionStorage if available
  const [formData, setFormData] = useState<SubmitReportFormData>(() => {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY_FORM);
      if (saved) {
        const parsed = JSON.parse(saved);
        return {
          ...DEFAULT_FORM_DATA,
          ...parsed,
          image: null,
        };
      }
    } catch {
      // ignore
    }
    return DEFAULT_FORM_DATA;
  });

  // Image file held in memory
  const [imageFile, setImageFileState] = useState<File | null>(null);

  // Image preview url (persisted in sessionStorage)
  const [imagePreviewUrl, setImagePreviewUrlState] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(STORAGE_KEY_IMAGE_PREVIEW);
    } catch {
      return null;
    }
  });

  // Re-hydrate image file from preview url if file is null but preview exists
  useEffect(() => {
    if (!imageFile && imagePreviewUrl && imagePreviewUrl.startsWith('data:')) {
      const reconstructed = dataUrlToFile(imagePreviewUrl);
      if (reconstructed) {
        setImageFileState(reconstructed);
        setFormData((prev) => ({ ...prev, image: reconstructed }));
      }
    }
  }, []);

  const setImageFile = (file: File | null) => {
    setImageFileState(file);
    setFormData((prev) => ({ ...prev, image: file }));
  };

  const setImagePreviewUrl = (url: string | null) => {
    setImagePreviewUrlState(url);
    try {
      if (url) {
        sessionStorage.setItem(STORAGE_KEY_IMAGE_PREVIEW, url);
      } else {
        sessionStorage.removeItem(STORAGE_KEY_IMAGE_PREVIEW);
      }
    } catch {
      // Storage quota or disabled
    }
  };

  // Submitted report confirmation
  const [submittedReport, setSubmittedReportState] = useState<DustReportResponse | null>(() => {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY_SUBMITTED);
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });

  const setSubmittedReport = (report: DustReportResponse | null) => {
    setSubmittedReportState(report);
    try {
      if (report) {
        sessionStorage.setItem(STORAGE_KEY_SUBMITTED, JSON.stringify(report));
      } else {
        sessionStorage.removeItem(STORAGE_KEY_SUBMITTED);
      }
    } catch {
      // ignore
    }
  };

  // Preserved state across other pages
  const [selectedReportIdInList, setSelectedReportIdInList] = useState<string | null>(null);
  const [mapSelectedReportId, setMapSelectedReportId] = useState<string | null>(null);
  const [mapStatusFilter, setMapStatusFilter] = useState<string>('all');

  // Save form fields to sessionStorage on change
  useEffect(() => {
    try {
      const { image, ...fieldsToSave } = formData;
      sessionStorage.setItem(STORAGE_KEY_FORM, JSON.stringify(fieldsToSave));
    } catch {
      // ignore
    }
  }, [formData]);

  const updateFormField = <K extends keyof SubmitReportFormData>(
    field: K,
    value: SubmitReportFormData[K]
  ) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  const resetDraft = () => {
    setFormData(DEFAULT_FORM_DATA);
    setImageFileState(null);
    setImagePreviewUrlState(null);
    setSubmittedReportState(null);
    try {
      sessionStorage.removeItem(STORAGE_KEY_FORM);
      sessionStorage.removeItem(STORAGE_KEY_IMAGE_PREVIEW);
      sessionStorage.removeItem(STORAGE_KEY_SUBMITTED);
    } catch {
      // ignore
    }
  };

  return (
    <ReportFormContext.Provider
      value={{
        formData,
        setFormData,
        updateFormField,
        imageFile,
        setImageFile,
        imagePreviewUrl,
        setImagePreviewUrl,
        submittedReport,
        setSubmittedReport,
        resetDraft,
        selectedReportIdInList,
        setSelectedReportIdInList,
        mapSelectedReportId,
        setMapSelectedReportId,
        mapStatusFilter,
        setMapStatusFilter,
      }}
    >
      {children}
    </ReportFormContext.Provider>
  );
};

export const useReportForm = (): ReportFormContextType => {
  const context = useContext(ReportFormContext);
  if (!context) {
    throw new Error('useReportForm must be used within a ReportFormProvider');
  }
  return context;
};
