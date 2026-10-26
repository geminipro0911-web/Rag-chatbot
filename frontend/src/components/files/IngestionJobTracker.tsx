import React, { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../../services/apiClient';
import { Loader2, CheckCircle, AlertTriangle, Sparkles, X } from 'lucide-react';
import { IngestionJobDTO } from '../../types/api';

interface Props {
  jobId: string;
  jobType: 'TABULAR' | 'DOCUMENT';
  onFinished: (job: IngestionJobDTO) => void;
  onDismiss?: () => void;
}

export const IngestionJobTracker: React.FC<Props> = ({
  jobId,
  jobType,
  onFinished,
  onDismiss,
}) => {
  const [hasNotified, setHasNotified] = useState(false);

  const { data: job } = useQuery({
    queryKey: ['upload-job', jobId],
    queryFn: () => apiClient.getUploadJobStatus(jobId),
    refetchInterval: (query) => {
      const current = query.state.data;
      if (current?.status === 'SUCCESS' || current?.status === 'FAILED') {
        return false;
      }
      return 1500; // 1.5s polling
    },
  });

  useEffect(() => {
    if (job && (job.status === 'SUCCESS' || job.status === 'FAILED') && !hasNotified) {
      setHasNotified(true);
      onFinished(job);
    }
  }, [job, hasNotified, onFinished]);

  if (!job) return null;

  const pct = job.progress_pct || 0;
  const isDone = job.status === 'SUCCESS';
  const isFailed = job.status === 'FAILED';

  // Informative phase description
  let phaseText = 'Đang khởi động tác vụ nạp dữ liệu...';
  if (isFailed) {
    phaseText = `Thất bại: ${job.error_message || 'Có lỗi xảy ra trong quá trình xử lý.'}`;
  } else if (isDone) {
    phaseText = 'Hoàn tất chỉ mục và sẵn sàng truy vấn!';
  } else if (pct < 20) {
    phaseText = 'Đang xếp hàng chờ & kiểm tra định dạng tệp...';
  } else if (pct < 60) {
    phaseText =
      jobType === 'TABULAR'
        ? 'Đang phân tích bảng tính, làm sạch ô gộp & lưu Parquet...'
        : 'Đang bóc tách cấu trúc tài liệu & phân đoạn ngữ nghĩa...';
  } else {
    phaseText =
      jobType === 'TABULAR'
        ? 'Đang sinh mô tả bảng & xác thực Few-Shot SQL...'
        : 'Đang nhúng BGE-M3 & cập nhật không gian Vector Qdrant...';
  }

  return (
    <div
      className={`p-3.5 rounded-2xl border shadow-sm animate-in fade-in-50 duration-200 ${
        isFailed
          ? 'bg-rose-50/80 dark:bg-rose-950/40 border-rose-300 dark:border-rose-900/60'
          : isDone
          ? 'bg-emerald-50/70 dark:bg-emerald-950/30 border-emerald-300 dark:border-emerald-800/50'
          : 'bg-slate-50 dark:bg-slate-800/80 border-slate-200 dark:border-slate-700/70'
      }`}
    >
      <div className="flex items-center justify-between text-xs mb-2">
        <div className="flex items-center gap-2 font-medium text-slate-800 dark:text-slate-200">
          {isDone ? (
            <CheckCircle className="w-4 h-4 text-emerald-500 flex-shrink-0" />
          ) : isFailed ? (
            <AlertTriangle className="w-4 h-4 text-rose-500 flex-shrink-0" />
          ) : (
            <Loader2 className="w-4 h-4 text-brand-500 animate-spin flex-shrink-0" />
          )}
          <span>{jobType === 'TABULAR' ? 'Xử lý Bảng tính' : 'Xử lý Văn bản'}</span>
          <span className="text-[11px] font-mono text-slate-400">({jobId.slice(0, 8)})</span>
        </div>

        <div className="flex items-center gap-2">
          <span
            className={`font-semibold ${
              isDone
                ? 'text-emerald-600 dark:text-emerald-400'
                : isFailed
                ? 'text-rose-600 dark:text-rose-400'
                : 'text-brand-600 dark:text-brand-400'
            }`}
          >
            {pct}%
          </span>

          {(isDone || isFailed) && onDismiss && (
            <button
              type="button"
              onClick={onDismiss}
              className="p-1 rounded-md text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
              title="Đóng thông báo"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Progress track */}
      <div className="w-full h-2 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden mb-2">
        <div
          className={`h-full transition-all duration-500 rounded-full ${
            isDone
              ? 'bg-emerald-500'
              : isFailed
              ? 'bg-rose-500'
              : 'bg-gradient-to-r from-brand-500 to-indigo-500'
          }`}
          style={{ width: `${Math.max(pct, 5)}%` }}
        />
      </div>

      <div
        className={`flex items-start gap-1.5 text-xs ${
          isFailed
            ? 'text-rose-700 dark:text-rose-300 font-medium'
            : 'text-slate-500 dark:text-slate-400'
        }`}
      >
        <Sparkles className="w-3.5 h-3.5 text-brand-500 flex-shrink-0 mt-0.5" />
        <span className="break-words leading-relaxed">{phaseText}</span>
      </div>
    </div>
  );
};
