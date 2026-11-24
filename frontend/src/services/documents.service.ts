import api from './api';

export type DocumentStatus = 'queued' | 'processing' | 'completed' | 'failed' | 'rejected';

export interface Document {
    id: string;
    filename: string;
    file_size: number;
    upload_date: string;
    status: DocumentStatus;
    progress: number;
    stage?: string | null;
    error_message?: string | null;
    rejection_reason?: string | null;
    page_count: number;
    chunk_count: number;
    mime_type?: string | null;
    is_medical?: number | null;
    domain_confidence?: number | null;
}

export interface UploadRejection {
    filename: string;
    reason: string;
}

export interface UploadResponse {
    documents: Document[];
    rejected: UploadRejection[];
    message?: string | null;
}

export interface DocumentListResponse {
    documents: Document[];
    total: number;
}

const documentsService = {
    upload: async (files: FileList, onProgress?: (progress: number) => void): Promise<UploadResponse> => {
        const formData = new FormData();
        Array.from(files).forEach((file) => {
            formData.append('files', file);
        });

        const response = await api.post<UploadResponse>('/api/v1/documents/upload', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
            onUploadProgress: (progressEvent) => {
                if (onProgress && progressEvent.total) {
                    const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
                    onProgress(progress);
                }
            },
        });

        return response.data;
    },

    list: async (): Promise<DocumentListResponse> => {
        const response = await api.get<DocumentListResponse>('/api/v1/documents');
        return response.data;
    },

    getStatus: async (docId: string): Promise<Document> => {
        const response = await api.get<Document>(`/api/v1/documents/${docId}/status`);
        return response.data;
    },

    delete: async (docId: string): Promise<void> => {
        await api.delete(`/api/v1/documents/${docId}`);
    },

    reindex: async (docId: string): Promise<void> => {
        await api.post(`/api/v1/documents/${docId}/reindex`);
    },

    getDownloadUrl: async (docId: string): Promise<{ url: string | null; expires_in: number }> => {
        const response = await api.get(`/api/v1/documents/${docId}/download`);
        return response.data;
    },
};

export default documentsService;
