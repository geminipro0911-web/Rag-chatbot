import React, { useRef, useState } from 'react';
import { UploadCloud, FileSpreadsheet, FileText, AlertCircle, CheckCircle2, Lock, Globe } from 'lucide-react';
import { apiClient } from '../../services/apiClient';
import { UploadApiResponse } from '../../types/api';

const SUPPORTED_EXTS = ['.xlsx', '.csv', '.pdf', '.docx', '.md', '.txt'];
const MAX_FILE_SIZE_BYTES = 30 * 1024 * 1024; // 30MB

interface Props {
  onUploadSuccess: (res: UploadApiResponse) => void;
}

export const FileUploadDropzone: React.FC<Props> = ({ onUploadSuccess }) => {
  const [isDragging, setIsDragging] = useState(false);
  const [isPublic, setIsPublic] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleValidateAndUpload = async (file: File) => {
    setErrorMsg(null);
    setSuccessMsg(null);

    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!SUPPORTED_EXTS.includes(ext)) {
      setErrorMsg(
        `Định dạng "${ext}" không được hỗ trợ. Chỉ chấp nhận .xlsx, .csv, .pdf, .docx, .md, .txt.`
      );
      return;
    }

    if (file.size > MAX_FILE_SIZE_BYTES) {
      setErrorMsg(
        `Dung lượng tệp (${(file.size / (1024 * 1024)).toFixed(1)}MB) vượt quá giới hạn tối đa 30MB.`
      );
      return;
    }

    try {
      setIsUploading(true);
      const res = await apiClient.uploadFile(file, isPublic);
      if (res.status === 'DUPLICATE') {
        setSuccessMsg(res.message);
      } else {
        setSuccessMsg(`Tải lên thành công tệp: ${file.name}`);
        onUploadSuccess(res);
      }
    } catch (err: any) {
      setErrorMsg(err.message || 'Tải tệp lên thất bại. Vui lòng thử lại.');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleValidateAndUpload(e.dataTransfer.files[0]);
    }
  };

  return (
    <div className="space-y-3">
      {/* Scope selector */}
      <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-100 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60">
        <div className="flex items-center gap-2 text-xs font-medium text-slate-700 dark:text-slate-300">
          {isPublic ? (
            <Globe className="w-4 h-4 text-emerald-500" />
          ) : (
            <Lock className="w-4 h-4 text-amber-500" />
          )}
          <span>Phạm vi tài liệu:</span>
          <span className="font-semibold text-slate-900 dark:text-slate-100">
            {isPublic ? 'Chia sẻ toàn công ty' : 'Nội bộ phòng ban'}
          </span>
        </div>

        <button
          type="button"
          onClick={() => setIsPublic(!isPublic)}
          className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
            isPublic ? 'bg-emerald-500' : 'bg-slate-300 dark:bg-slate-700'
          }`}
        >
          <span
            className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
              isPublic ? 'translate-x-4' : 'translate-x-0'
            }`}
          />
        </button>
      </div>

      {/* Dropzone Container */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`group relative flex flex-col items-center justify-center p-6 border-2 border-dashed rounded-2xl cursor-pointer transition-all duration-200 text-center ${
          isDragging
            ? 'border-brand-500 bg-brand-50/50 dark:bg-brand-950/20'
            : 'border-slate-300 dark:border-slate-700 hover:border-brand-400 dark:hover:border-brand-500 bg-white dark:bg-slate-900'
        }`}
      >
        <input
          type="file"
          ref={fileInputRef}
          className="hidden"
          accept=".xlsx,.csv,.pdf,.docx,.md,.txt"
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) {
              handleValidateAndUpload(e.target.files[0]);
            }
          }}
          disabled={isUploading}
        />

        <div className="w-12 h-12 rounded-2xl bg-brand-50 dark:bg-brand-950/40 text-brand-600 dark:text-brand-400 flex items-center justify-center mb-3 group-hover:scale-110 transition-transform">
          <UploadCloud className="w-6 h-6" />
        </div>

        <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          {isUploading ? 'Đang chuẩn bị và gửi tệp...' : 'Kéo thả tệp hoặc nhấp để tải lên'}
        </p>

        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          Hỗ trợ .xlsx, .csv, .pdf, .docx, .md, .txt (tối đa 30MB)
        </p>
      </div>

      {/* Messages */}
      {errorMsg && (
        <div className="flex items-center gap-2 p-2.5 rounded-xl bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/40 text-xs text-rose-700 dark:text-rose-300">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {successMsg && (
        <div className="flex items-center gap-2 p-2.5 rounded-xl bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-900/40 text-xs text-emerald-700 dark:text-emerald-300">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}
    </div>
  );
};
