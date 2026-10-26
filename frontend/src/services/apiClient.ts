import axios, { AxiosError } from 'axios';
import {
  ChatApiResponse,
  ChatMessageDTO,
  ChatRequest,
  ChatSessionDTO,
  FeedbackRequest,
  FileItemDTO,
  HealthResponse,
  IngestionJobDTO,
  UploadApiResponse,
  UserMeResponse,
} from '../types/api';

const api = axios.create({
  baseURL: '/',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 120000, // 2 minutes for heavy LLM / DuckDB queries
});

// Response interceptor for clear enterprise error handling
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: string }>) => {
    const errorMsg =
      error.response?.data?.detail ||
      error.message ||
      'Đã xảy ra lỗi khi kết nối tới máy chủ.';
    console.error(`[API Error ${error.response?.status}]:`, errorMsg);
    return Promise.reject(new Error(errorMsg));
  }
);

export const apiClient = {
  // Auth & Profile
  getMe: async (): Promise<UserMeResponse> => {
    const res = await api.get<UserMeResponse>('/me');
    return res.data;
  },

  // System Health
  getHealth: async (): Promise<HealthResponse> => {
    const res = await api.get<HealthResponse>('/health');
    return res.data;
  },

  // Knowledge & Data Vault (Files)
  getFiles: async (params?: {
    department_id?: string;
    is_public_only?: boolean;
  }): Promise<FileItemDTO[]> => {
    const res = await api.get<FileItemDTO[]>('/files', { params });
    return res.data;
  },

  uploadFile: async (
    file: File,
    isPublic: boolean,
    departmentId?: string
  ): Promise<UploadApiResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('is_public', String(isPublic));
    if (departmentId) {
      formData.append('department_id', departmentId);
    }
    const res = await api.post<UploadApiResponse>('/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return res.data;
  },

  getUploadJobStatus: async (jobId: string): Promise<IngestionJobDTO> => {
    const res = await api.get<IngestionJobDTO>(`/upload/${jobId}`);
    return res.data;
  },

  deleteFile: async (
    fileId: string
  ): Promise<{ status: string; file_id: string; message: string }> => {
    const res = await api.delete<{
      status: string;
      file_id: string;
      message: string;
    }>(`/files/${fileId}`);
    return res.data;
  },

  // Chat Sessions & Messages
  getSessions: async (): Promise<ChatSessionDTO[]> => {
    const res = await api.get<ChatSessionDTO[]>('/sessions');
    return res.data;
  },

  getSessionMessages: async (sessionId: string): Promise<ChatMessageDTO[]> => {
    const res = await api.get<ChatMessageDTO[]>(
      `/sessions/${sessionId}/messages`
    );
    return res.data;
  },

  deleteSession: async (
    sessionId: string
  ): Promise<{ status: string; session_id: string; message: string }> => {
    const res = await api.delete<{
      status: string;
      session_id: string;
      message: string;
    }>(`/sessions/${sessionId}`);
    return res.data;
  },

  sendChatMessage: async (data: ChatRequest): Promise<ChatApiResponse> => {
    const res = await api.post<ChatApiResponse>('/chat', data);
    return res.data;
  },

  submitFeedback: async (
    data: FeedbackRequest
  ): Promise<{
    status: string;
    message_id: string;
    feedback: string;
    promoted_fewshot: boolean;
    message: string;
  }> => {
    const res = await api.post('/feedback', data);
    return res.data;
  },
};
