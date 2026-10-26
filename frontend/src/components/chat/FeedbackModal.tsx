import React, { useState } from 'react';
import { ThumbsUp, ThumbsDown, Check, X, Loader2, Wrench, MessageSquare, Code2 } from 'lucide-react';
import { apiClient } from '../../services/apiClient';

interface Props {
  messageId: string;
  initialFeedback?: 'positive' | 'negative' | 'thumbs_up' | 'thumbs_down' | null;
  defaultSql?: string | null;
  onFeedbackSaved: (feedback: 'thumbs_up' | 'thumbs_down') => void;
}

export const FeedbackModal: React.FC<Props> = ({
  messageId,
  initialFeedback,
  defaultSql,
  onFeedbackSaved,
}) => {
  const [currentFeedback, setCurrentFeedback] = useState<
    'thumbs_up' | 'thumbs_down' | null
  >(() => {
    if (initialFeedback === 'positive' || initialFeedback === 'thumbs_up') return 'thumbs_up';
    if (initialFeedback === 'negative' || initialFeedback === 'thumbs_down') return 'thumbs_down';
    return null;
  });

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<'thumbs_up_edit' | 'thumbs_down'>('thumbs_down');
  const [comment, setComment] = useState('');
  const [suggestedSql, setSuggestedSql] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Quick thumbs up submit
  const handleQuickThumbsUp = async () => {
    try {
      setIsSubmitting(true);
      await apiClient.submitFeedback({
        message_id: messageId,
        feedback_type: 'thumbs_up',
      });
      setCurrentFeedback('thumbs_up');
      onFeedbackSaved('thumbs_up');
    } catch (err) {
      console.error(err);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleOpenEditModal = (mode: 'thumbs_up_edit' | 'thumbs_down') => {
    setModalMode(mode);
    setSuggestedSql(defaultSql || '');
    setComment('');
    setSubmitError(null);
    setIsModalOpen(true);
  };

  const handleSubmitModal = async () => {
    try {
      setIsSubmitting(true);
      setSubmitError(null);
      const feedbackType = modalMode === 'thumbs_up_edit' ? 'thumbs_up' : 'thumbs_down';
      await apiClient.submitFeedback({
        message_id: messageId,
        feedback_type: feedbackType,
        comment: comment.trim() || undefined,
        suggested_sql: suggestedSql.trim() || undefined,
      });
      setCurrentFeedback(feedbackType);
      onFeedbackSaved(feedbackType);
      setIsModalOpen(false);
    } catch (err: any) {
      console.error(err);
      setSubmitError(err.message || 'Không thể gửi phản hồi. Vui lòng kiểm tra lại câu SQL hoặc kết nối.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex items-center gap-1.5 pt-2">
      {/* Thumbs Up Button */}
      <button
        type="button"
        onClick={handleQuickThumbsUp}
        disabled={isSubmitting || currentFeedback === 'thumbs_up'}
        className={`p-1.5 rounded-lg text-xs transition-colors ${
          currentFeedback === 'thumbs_up'
            ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-700'
            : 'text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800'
        }`}
        title="Đánh giá câu trả lời chính xác và hữu ích"
      >
        <ThumbsUp className="w-3.5 h-3.5" />
      </button>

      {/* If SQL is present, provide few-shot promotion/editing button */}
      {defaultSql && (
        <button
          type="button"
          onClick={() => handleOpenEditModal('thumbs_up_edit')}
          className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium text-brand-600 dark:text-brand-400 hover:bg-brand-50 dark:hover:bg-brand-950/40 transition-colors"
          title="Kiểm tra & chỉnh sửa câu SQL mẫu để nạp vào bộ nhớ Few-Shot"
        >
          <Wrench className="w-3 h-3" />
          <span>Xác nhận SQL mẫu</span>
        </button>
      )}

      {/* Thumbs Down Button */}
      <button
        type="button"
        onClick={() => handleOpenEditModal('thumbs_down')}
        disabled={isSubmitting || currentFeedback === 'thumbs_down'}
        className={`p-1.5 rounded-lg text-xs transition-colors ${
          currentFeedback === 'thumbs_down'
            ? 'bg-rose-50 text-rose-600 dark:bg-rose-950/50 dark:text-rose-400 border border-rose-300 dark:border-rose-700'
            : 'text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800'
        }`}
        title="Báo cáo câu trả lời chưa chính xác"
      >
        <ThumbsDown className="w-3.5 h-3.5" />
      </button>

      {/* Modal Dialog */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="w-full max-w-lg p-5 bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-800 animate-in zoom-in-95 duration-150 text-xs">
            {/* Header */}
            <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2 font-bold text-sm text-slate-900 dark:text-slate-100">
                {modalMode === 'thumbs_up_edit' ? (
                  <>
                    <Wrench className="w-4 h-4 text-brand-500" />
                    <span>Chỉnh sửa & Thăng Hạng SQL Mẫu (Verified Few-Shot)</span>
                  </>
                ) : (
                  <>
                    <ThumbsDown className="w-4 h-4 text-rose-500" />
                    <span>Góp ý Phản hồi & Dạy lại Hệ thống</span>
                  </>
                )}
              </div>
              <button
                type="button"
                onClick={() => setIsModalOpen(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3.5">
              {submitError && (
                <div className="p-2.5 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-xs text-rose-600 dark:text-rose-400">
                  {submitError}
                </div>
              )}

              {/* Comment field */}
              <div>
                <label className="block text-[11px] font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wider mb-1 flex items-center gap-1">
                  <MessageSquare className="w-3 h-3" /> Ghi chú phản hồi:
                </label>
                <textarea
                  rows={2}
                  placeholder={
                    modalMode === 'thumbs_up_edit'
                      ? 'Ghi chú về tính huống sử dụng câu SQL này (tùy chọn)...'
                      : 'Mô tả chi tiết câu trả lời chưa đúng ở điểm nào...'
                  }
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  className="w-full p-2.5 rounded-xl bg-slate-50 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
              </div>

              {/* SQL Field */}
              <div>
                <label className="block text-[11px] font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wider mb-1 flex items-center gap-1">
                  <Code2 className="w-3 h-3" /> Câu lệnh SQL chuẩn xác (Suggested SQL):
                </label>
                <textarea
                  rows={5}
                  placeholder="SELECT ... FROM ... WHERE ..."
                  value={suggestedSql}
                  onChange={(e) => setSuggestedSql(e.target.value)}
                  className="w-full p-2.5 rounded-xl bg-slate-950 text-slate-100 font-mono text-[11px] border border-slate-800 focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
                <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-1">
                  Câu SQL này sẽ được hệ thống kiểm tra sandbox an toàn trước khi lưu vào danh mục Few-Shot.
                </p>
              </div>
            </div>

            {/* Footer Buttons */}
            <div className="flex items-center justify-end gap-2 pt-4 mt-2 border-t border-slate-100 dark:border-slate-800">
              <button
                type="button"
                onClick={() => setIsModalOpen(false)}
                className="px-3.5 py-1.5 rounded-xl text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 font-medium"
              >
                Hủy bỏ
              </button>

              <button
                type="button"
                onClick={handleSubmitModal}
                disabled={isSubmitting}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-xl font-semibold text-white bg-brand-600 hover:bg-brand-700 shadow-sm transition-all disabled:opacity-50"
              >
                {isSubmitting ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Check className="w-3.5 h-3.5" />
                )}
                <span>Lưu phản hồi</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
