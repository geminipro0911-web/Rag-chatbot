import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../../services/apiClient';
import {
  X,
  Search,
  Database,
  Filter,
  Plus,
  RefreshCw,
  FolderOpen,
} from 'lucide-react';
import { FileCardItem } from './FileCardItem';
import { FileUploadDropzone } from './FileUploadDropzone';
import { IngestionJobTracker } from './IngestionJobTracker';
import { IngestionJobDTO, UploadApiResponse } from '../../types/api';

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export const FileVaultDrawer: React.FC<Props> = ({ isOpen, onClose }) => {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'all' | 'tabular' | 'document'>('all');
  const [scopeFilter, setScopeFilter] = useState<'all' | 'public' | 'department'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [showUploadArea, setShowUploadArea] = useState(false);
  const [activeJobs, setActiveJobs] = useState<
    { jobId: string; jobType: 'TABULAR' | 'DOCUMENT' }[]
  >([]);

  const {
    data: files = [],
    isLoading,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['files-vault'],
    queryFn: () => apiClient.getFiles(),
    enabled: isOpen,
  });

  const handleUploadSuccess = (res: UploadApiResponse) => {
    if (res.job_id) {
      setActiveJobs((prev) => [
        {
          jobId: res.job_id!,
          jobType: res.job_type || 'DOCUMENT',
        },
        ...prev,
      ]);
    }
  };

  const handleJobFinished = (job: IngestionJobDTO) => {
    // Refresh files list
    queryClient.invalidateQueries({ queryKey: ['files-vault'] });

    // Auto-dismiss successful jobs after 2500ms
    if (job.status === 'SUCCESS') {
      setTimeout(() => {
        setActiveJobs((prev) => prev.filter((j) => j.jobId !== job.job_id));
      }, 2500);
    }
  };

  const handleDismissJob = (jobId: string) => {
    setActiveJobs((prev) => prev.filter((j) => j.jobId !== jobId));
  };

  const handleDeleteFile = async (fileId: string) => {
    await apiClient.deleteFile(fileId);
    queryClient.invalidateQueries({ queryKey: ['files-vault'] });
  };

  if (!isOpen) return null;

  // Filter files
  const filteredFiles = files.filter((f) => {
    const ext = f.file_type.toLowerCase();
    const isTab = ext === 'xlsx' || ext === 'csv' || ext === 'xls';

    if (activeTab === 'tabular' && !isTab) return false;
    if (activeTab === 'document' && isTab) return false;

    if (scopeFilter === 'public' && !f.is_public) return false;
    if (scopeFilter === 'department' && f.is_public) return false;

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchName = f.file_name.toLowerCase().includes(q);
      const matchSheet = f.tables_catalog?.some((t) =>
        t.sheet_name.toLowerCase().includes(q)
      );
      if (!matchName && !matchSheet) return false;
    }

    return true;
  });

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-xl h-full bg-white dark:bg-slate-950 shadow-2xl border-l border-slate-200 dark:border-slate-800 flex flex-col animate-in slide-in-from-right duration-250">
        {/* Header */}
        <div className="p-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-brand-50 dark:bg-brand-950/40 text-brand-600 dark:text-brand-400 flex items-center justify-center">
              <Database className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                Kho Tri thức & Dữ liệu
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 font-normal">
                  {files.length} tệp
                </span>
              </h2>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                Tài liệu & Bảng tính được phân quyền truy cập
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1">
            <button
              onClick={() => refetch()}
              className="p-2 rounded-xl text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              title="Làm mới danh sách"
            >
              <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin text-brand-500' : ''}`} />
            </button>
            <button
              onClick={onClose}
              className="p-2 rounded-xl text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              title="Đóng ngăn dữ liệu"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Content body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Toggle Upload button */}
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={() => setShowUploadArea(!showUploadArea)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-white bg-brand-600 hover:bg-brand-700 shadow-sm transition-all"
            >
              <Plus className="w-3.5 h-3.5" />
              {showUploadArea ? 'Thu gọn tải tệp' : 'Tải tệp mới lên'}
            </button>

            {/* Scope filter selector */}
            <select
              value={scopeFilter}
              onChange={(e) => setScopeFilter(e.target.value as any)}
              className="text-xs font-medium rounded-xl bg-slate-100 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 px-2.5 py-1.5 text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-brand-500"
            >
              <option value="all">Tất cả phạm vi</option>
              <option value="public">Toàn công ty</option>
              <option value="department">Nội bộ phòng ban</option>
            </select>
          </div>

          {/* Upload Area */}
          {showUploadArea && (
            <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 animate-in fade-in-50 duration-200">
              <FileUploadDropzone onUploadSuccess={handleUploadSuccess} />
            </div>
          )}

          {/* Active Job Trackers */}
          {activeJobs.length > 0 && (
            <div className="space-y-2">
              <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                Tiến trình nạp tệp thời gian thực:
              </span>
              {activeJobs.map((j) => (
                <IngestionJobTracker
                  key={j.jobId}
                  jobId={j.jobId}
                  jobType={j.jobType}
                  onFinished={handleJobFinished}
                  onDismiss={() => handleDismissJob(j.jobId)}
                />
              ))}
            </div>
          )}

          {/* Search bar & Tabs */}
          <div className="space-y-2">
            <div className="relative">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Tìm kiếm theo tên file hoặc tên sheet..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-4 py-2 text-xs rounded-xl bg-slate-100 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 focus:outline-none focus:ring-2 focus:ring-brand-500 dark:focus:ring-brand-400 text-slate-800 dark:text-slate-200"
              />
            </div>

            <div className="flex p-1 rounded-xl bg-slate-100 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 text-xs">
              <button
                type="button"
                onClick={() => setActiveTab('all')}
                className={`flex-1 py-1.5 rounded-lg font-medium transition-all ${
                  activeTab === 'all'
                    ? 'bg-white dark:bg-slate-900 text-brand-600 dark:text-brand-400 shadow-sm'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                }`}
              >
                Tất cả ({files.length})
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('tabular')}
                className={`flex-1 py-1.5 rounded-lg font-medium transition-all ${
                  activeTab === 'tabular'
                    ? 'bg-white dark:bg-slate-900 text-brand-600 dark:text-brand-400 shadow-sm'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                }`}
              >
                Bảng tính ({files.filter((f) => ['xlsx', 'csv', 'xls'].includes(f.file_type.toLowerCase())).length})
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('document')}
                className={`flex-1 py-1.5 rounded-lg font-medium transition-all ${
                  activeTab === 'document'
                    ? 'bg-white dark:bg-slate-900 text-brand-600 dark:text-brand-400 shadow-sm'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                }`}
              >
                Văn bản ({files.filter((f) => !['xlsx', 'csv', 'xls'].includes(f.file_type.toLowerCase())).length})
              </button>
            </div>
          </div>

          {/* Files List */}
          <div className="space-y-2.5">
            {isLoading ? (
              <div className="space-y-3 py-6">
                {[1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="p-4 rounded-2xl bg-slate-100/60 dark:bg-slate-800/40 animate-pulse h-20"
                  />
                ))}
              </div>
            ) : filteredFiles.length === 0 ? (
              <div className="text-center py-12 px-4">
                <FolderOpen className="w-12 h-12 text-slate-300 dark:text-slate-700 mx-auto mb-3" />
                <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                  Không tìm thấy tệp phù hợp
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  Hãy thử thay đổi bộ lọc hoặc tải thêm tệp mới vào kho dữ liệu.
                </p>
              </div>
            ) : (
              filteredFiles.map((file) => (
                <FileCardItem
                  key={file.id}
                  file={file}
                  onDelete={handleDeleteFile}
                />
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
