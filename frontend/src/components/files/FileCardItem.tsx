import React, { useState } from 'react';
import {
  FileSpreadsheet,
  FileText,
  FileCode,
  Trash2,
  ChevronDown,
  ChevronUp,
  Globe,
  Lock,
  Layers,
  BookOpen,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import { FileItemDTO } from '../../types/api';
import { formatBytes, formatDate } from '../../utils/formatters';

interface Props {
  file: FileItemDTO;
  onDelete: (fileId: string) => Promise<void>;
}

export const FileCardItem: React.FC<Props> = ({ file, onDelete }) => {
  const [expanded, setExpanded] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const ext = file.file_type.toLowerCase();
  const isTabular = ext === 'xlsx' || ext === 'csv' || ext === 'xls';
  const isPdf = ext === 'pdf';
  const isWord = ext === 'docx' || ext === 'doc';

  const renderIcon = () => {
    if (isTabular) {
      return (
        <div className="w-10 h-10 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 flex items-center justify-center flex-shrink-0">
          <FileSpreadsheet className="w-5 h-5" />
        </div>
      );
    }
    if (isPdf) {
      return (
        <div className="w-10 h-10 rounded-xl bg-rose-50 dark:bg-rose-950/40 text-rose-600 dark:text-rose-400 flex items-center justify-center flex-shrink-0">
          <FileText className="w-5 h-5" />
        </div>
      );
    }
    if (isWord) {
      return (
        <div className="w-10 h-10 rounded-xl bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 flex items-center justify-center flex-shrink-0">
          <FileText className="w-5 h-5" />
        </div>
      );
    }
    return (
      <div className="w-10 h-10 rounded-xl bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 flex items-center justify-center flex-shrink-0">
        <FileCode className="w-5 h-5" />
      </div>
    );
  };

  const handleDelete = async () => {
    try {
      setIsDeleting(true);
      await onDelete(file.id);
    } finally {
      setIsDeleting(false);
      setShowConfirm(false);
    }
  };

  const sheetsCount = file.tables_catalog?.length || 0;
  const docsCount = file.documents?.length || 0;

  return (
    <div className="p-3.5 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start gap-3">
        {renderIcon()}

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h4
              className="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate"
              title={file.file_name}
            >
              {file.file_name}
            </h4>

            {file.is_public ? (
              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
                <Globe className="w-2.5 h-2.5" />
                Công khai
              </span>
            ) : (
              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                <Lock className="w-2.5 h-2.5" />
                {file.department_id}
              </span>
            )}
          </div>

          <div className="flex items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400 mt-1">
            <span>{formatBytes(file.file_size_bytes)}</span>
            <span>•</span>
            <span>{formatDate(file.created_at)}</span>

            {isTabular && sheetsCount > 0 && (
              <>
                <span>•</span>
                <span className="text-brand-600 dark:text-brand-400 font-medium">
                  {sheetsCount} Sheet
                </span>
              </>
            )}

            {!isTabular && docsCount > 0 && (
              <>
                <span>•</span>
                <span className="text-brand-600 dark:text-brand-400 font-medium">
                  {file.documents[0]?.total_pages || 1} Trang
                </span>
              </>
            )}
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-1">
          {(sheetsCount > 0 || docsCount > 0) && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              title={expanded ? 'Thu gọn' : 'Xem chi tiết bảng/trang'}
            >
              {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
          )}

          {file.can_delete && (
            <button
              onClick={() => setShowConfirm(true)}
              className="p-1.5 rounded-lg text-rose-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors"
              title="Xóa tệp và dữ liệu chỉ mục"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Expanded details (Sheets / Documents) */}
      {expanded && (
        <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-800/80 space-y-2 text-xs">
          {isTabular && file.tables_catalog && file.tables_catalog.length > 0 && (
            <div className="space-y-1.5">
              <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-1">
                <Layers className="w-3 h-3" /> Danh sách Sheet đã nạp:
              </span>
              <div className="grid gap-1.5">
                {file.tables_catalog.map((tbl) => (
                  <div
                    key={tbl.id}
                    className="p-2 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200/60 dark:border-slate-700/40 flex items-center justify-between"
                  >
                    <div>
                      <span className="font-semibold text-slate-800 dark:text-slate-200">
                        {tbl.sheet_name}
                      </span>
                      {tbl.table_description && (
                        <p className="text-[11px] text-slate-500 dark:text-slate-400 line-clamp-1">
                          {tbl.table_description}
                        </p>
                      )}
                    </div>
                    <span className="font-mono text-[11px] font-semibold text-slate-600 dark:text-slate-300 px-2 py-0.5 rounded bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700">
                      {tbl.row_count.toLocaleString()} dòng
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {!isTabular && file.documents && file.documents.length > 0 && (
            <div className="space-y-1.5">
              <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-1">
                <BookOpen className="w-3 h-3" /> Cấu trúc văn bản:
              </span>
              <div className="p-2 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200/60 dark:border-slate-700/40 text-[11px] text-slate-600 dark:text-slate-300 flex items-center justify-between">
                <span>Tổng số trang & đoạn trích:</span>
                <span className="font-semibold text-brand-600 dark:text-brand-400">
                  {file.documents[0]?.total_pages} trang • {file.documents[0]?.total_chunks} chunks
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="w-full max-w-sm p-5 bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-800 animate-in zoom-in-95 duration-150">
            <div className="flex items-center gap-3 text-rose-600 dark:text-rose-400 mb-3">
              <div className="p-2.5 rounded-xl bg-rose-50 dark:bg-rose-950/40">
                <AlertCircle className="w-6 h-6" />
              </div>
              <h3 className="font-semibold text-base text-slate-900 dark:text-slate-100">
                Xác nhận xóa tệp?
              </h3>
            </div>

            <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed mb-4">
              Bạn có chắc chắn muốn xóa tệp <strong className="font-semibold text-slate-800 dark:text-slate-200">"{file.file_name}"</strong>?
              Thao tác này sẽ xóa vĩnh viễn tệp gốc, bảng số liệu Parquet và toàn bộ vector chỉ mục liên quan.
            </p>

            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowConfirm(false)}
                disabled={isDeleting}
                className="px-3.5 py-1.5 rounded-xl text-xs font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                Hủy bỏ
              </button>
              <button
                type="button"
                onClick={handleDelete}
                disabled={isDeleting}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-xl text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 transition-colors shadow-sm disabled:opacity-50"
              >
                {isDeleting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                Xóa ngay
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
