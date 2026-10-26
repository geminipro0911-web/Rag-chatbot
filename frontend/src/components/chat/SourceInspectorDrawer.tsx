import React, { useEffect, useRef } from 'react';
import { SourceCitation } from '../../types/api';
import { X, FileText, ShieldCheck, Quote, Copy, Check } from 'lucide-react';
import { formatScorePct } from '../../utils/formatters';

interface Props {
  isOpen: boolean;
  sources: SourceCitation[];
  highlightIndex: number | null;
  onClose: () => void;
}

export const SourceInspectorDrawer: React.FC<Props> = ({
  isOpen,
  sources,
  highlightIndex,
  onClose,
}) => {
  const cardRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const [copiedIndex, setCopiedIndex] = React.useState<number | null>(null);

  useEffect(() => {
    if (isOpen && highlightIndex && cardRefs.current[highlightIndex]) {
      cardRefs.current[highlightIndex]?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    }
  }, [isOpen, highlightIndex]);

  const handleCopyQuote = async (text: string, idx: number) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIndex(idx);
      setTimeout(() => setCopiedIndex(null), 2000);
    } catch (e) {
      console.error(e);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-lg h-full bg-white dark:bg-slate-950 shadow-2xl border-l border-slate-200 dark:border-slate-800 flex flex-col animate-in slide-in-from-right duration-250">
        {/* Header */}
        <div className="p-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-brand-50 dark:bg-brand-950/40 text-brand-600 dark:text-brand-400 flex items-center justify-center">
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                Nguồn Trích Dẫn & Căn Cứ
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 font-normal">
                  {sources.length} nguồn
                </span>
              </h2>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                Chi tiết các đoạn trích từ tài liệu gốc được AI tham chiếu
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 rounded-xl text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Sources List */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3.5">
          {sources.length === 0 ? (
            <div className="text-center py-12 text-slate-500 dark:text-slate-400 text-xs">
              Không có nguồn tham khảo nào cho câu trả lời này.
            </div>
          ) : (
            sources.map((src) => {
              const isTarget = highlightIndex === src.index;

              return (
                <div
                  key={src.index}
                  ref={(el) => (cardRefs.current[src.index] = el)}
                  className={`p-4 rounded-2xl border transition-all duration-300 ${
                    isTarget
                      ? 'bg-brand-50/60 dark:bg-brand-950/30 border-brand-500 ring-2 ring-brand-500/20 shadow-md'
                      : 'bg-slate-50/60 dark:bg-slate-900 border-slate-200 dark:border-slate-800'
                  }`}
                >
                  {/* Top line: Citation Pill + File name + Page */}
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="flex-shrink-0 px-2 py-0.5 rounded-md font-mono font-bold text-xs bg-brand-600 text-white shadow-xs">
                        [{src.index}]
                      </span>
                      <h4
                        className="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate"
                        title={src.file_name}
                      >
                        {src.file_name}
                      </h4>
                    </div>

                    {src.page !== null && src.page !== undefined && (
                      <span className="flex-shrink-0 px-2 py-0.5 rounded text-[11px] font-medium bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300">
                        Trang {src.page}
                      </span>
                    )}
                  </div>

                  {/* Section Title */}
                  {src.section_title && (
                    <div className="text-[11px] font-semibold text-brand-700 dark:text-brand-300 mb-2">
                      📍 {src.section_title}
                    </div>
                  )}

                  {/* Quoted Text */}
                  <div className="relative p-3 rounded-xl bg-white dark:bg-slate-950/70 border border-slate-200/80 dark:border-slate-800 text-xs text-slate-700 dark:text-slate-300 leading-relaxed font-sans mb-2">
                    <div className="flex items-start gap-2">
                      <Quote className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
                      <p className="whitespace-pre-wrap">{src.quote}</p>
                    </div>

                    <button
                      type="button"
                      onClick={() => handleCopyQuote(src.quote, src.index)}
                      className="absolute top-2 right-2 p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                      title="Sao chép trích dẫn"
                    >
                      {copiedIndex === src.index ? (
                        <Check className="w-3.5 h-3.5 text-emerald-500" />
                      ) : (
                        <Copy className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>

                  {/* Confidence Score Bar */}
                  {src.score !== null && src.score !== undefined && (
                    <div className="flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400 pt-1">
                      <span className="flex items-center gap-1">
                        <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
                        Điểm phù hợp Reranker:
                      </span>
                      <span className="font-semibold text-emerald-600 dark:text-emerald-400 font-mono">
                        {formatScorePct(src.score)}
                      </span>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
