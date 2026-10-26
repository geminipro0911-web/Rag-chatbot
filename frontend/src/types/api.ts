/**
 * API Type Definitions for Mbot Enterprise RAG & Tabular Execution System.
 * Matches 100% with Backend FastAPI DTOs.
 */

export interface UserMeResponse {
  user_id: string;
  full_name: string;
  department_id: string;
  role: string;
  is_admin: boolean;
}

export interface HealthResponse {
  status: 'healthy' | 'degraded' | 'unhealthy';
  database: string;
  vector_store: string;
  app_env: string;
  timezone: string;
}

export interface IngestionJobDTO {
  job_id: string;
  file_id?: string;
  job_type: 'TABULAR' | 'DOCUMENT';
  status: 'PENDING' | 'PROCESSING' | 'SUCCESS' | 'FAILED';
  progress_pct: number;
  error_message?: string | null;
  created_at?: string | null;
  finished_at?: string | null;
}

export interface TableSummaryDTO {
  id: string;
  sheet_name: string;
  row_count: number;
  table_description?: string | null;
  business_keywords?: string[];
}

export interface DocSummaryDTO {
  id: string;
  title: string;
  total_pages: number;
  total_chunks: number;
}

export interface FileItemDTO {
  id: string;
  file_name: string;
  file_type: string;
  file_size_bytes: number;
  sha256_hash: string;
  department_id: string;
  owner_user_id: string;
  is_public: boolean;
  created_at: string;
  updated_at?: string | null;
  latest_job?: IngestionJobDTO | null;
  tables_catalog: TableSummaryDTO[];
  documents: DocSummaryDTO[];
  can_delete: boolean;
}

export interface ChatSessionDTO {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface SourceCitation {
  index: number;
  file_name: string;
  page?: number | null;
  section_title?: string | null;
  quote: string;
  score?: number | null;
}

export interface TableResultDTO {
  table_name: string;
  file_name: string;
  sheet_name: string;
  total_rows: number;
  displayed_rows: number;
  columns: string[];
}

export interface DebugInfo {
  rewritten_query: string;
  language: string;
  code?: string | null;
  attempts?: number;
  latency_ms?: number;
  rerank_scores?: number[];
}

export type ExecutionRoute =
  | 'TABULAR'
  | 'DOCUMENT'
  | 'HYBRID'
  | 'CLARIFY'
  | 'CHITCHAT'
  | 'OUT_OF_SCOPE';

export interface ChatMessageDTO {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  latency_ms?: number;
  created_at?: string | null;
  route?: ExecutionRoute | null;
  sources?: SourceCitation[];
  tables?: TableResultDTO[];
  debug?: DebugInfo | null;
  feedback?: 'positive' | 'negative' | 'thumbs_up' | 'thumbs_down' | null;
}

export interface ChatRequest {
  message: string;
  session_id?: string | null;
  is_public_only?: boolean;
}

export interface ChatApiResponse {
  session_id: string;
  message_id: string;
  answer_markdown: string;
  route: ExecutionRoute;
  sources: SourceCitation[];
  tables: TableResultDTO[];
  debug?: DebugInfo | null;
}

export interface UploadApiResponse {
  status: 'PENDING' | 'DUPLICATE';
  job_id?: string;
  file_id: string;
  job_type?: 'TABULAR' | 'DOCUMENT';
  message: string;
}

export interface FeedbackRequest {
  message_id: string;
  feedback_type: 'thumbs_up' | 'thumbs_down';
  comment?: string | null;
  suggested_sql?: string | null;
}
