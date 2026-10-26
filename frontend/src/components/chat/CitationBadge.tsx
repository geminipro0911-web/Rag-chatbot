import React, { useState } from 'react';
import { SourceCitation } from '../../types/api';
import { FileText, ExternalLink, ShieldCheck, Quote } from 'lucide-react';
import { formatScorePct } from '../../utils/formatters';

interface Props {
  index: number;
  source?: SourceCitation;
  onClick: (index: number) => void;
}

export const CitationBadge: React.FC<Props> = ({ index, source, onClick }) => {
  const [showPopover, setShowPopover] = useState(false);

  return (
    <span className="relative inline-block mx-0.5 align-baseline">
      <button
        type="button"
        onClick={() => onClick(index)}
        onMouseEnter={() => setShowPopover(true)}
        onMouseLeave={() => setShowPopover(false)}
        className="inline-flex items-center justify-center px-1.5 py-0.5 text-[11px] font-bold font-mono text-brand-700 dark:text-brand-300 bg-brand-50 hover:bg-brand-100 dark:bg-brand-950/60 dark:hover:bg-brand-900/60 border border-brand-200/80 dark:border-brand-800/80 rounded-md transition-all cursor-pointer shadow-xs hover:scale-105"
        title="Nhấp để xem chi tiết trích dẫn trong Drawer"
      >
        [{index}]
      </button>

      {/* Hover Popover - Uses <span> tags to prevent HTML validateDOMNesting issues when inside <p> */}
      {showPopover && source && (
        <span
          onMouseEnter={() => setShowPopover(true)}
          onMouseLeave={() => setShowPopover(false)}
          className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-50 w-72 sm:w-80 p-3 bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-800 text-xs text-slate-700 dark:text-slate-300 animate-in fade-in zoom-in-95 duration-150 pointer-events-auto block text-left font-normal"
        >
          {/* Header */}
          <span className="flex items-start justify-between gap-2 pb-2 mb-2 border-b border-slate-100 dark:border-slate-800">
            <span className="flex items-center gap-1.5 min-w-0">
              <FileText className="w-4 h-4 text-brand-600 dark:text-brand-400 flex-shrink-0" />
              <span
                className="font-semibold text-slate-900 dark:text-slate-100 truncate block"
                title={source.file_name}
              >
                {source.file_name}
              </span>
            </span>

            {source.page !== null && source.page !== undefined && (
              <span className="flex-shrink-0 px-1.5 py-0.5 rounded bg-brand-50 dark:bg-brand-950/50 text-brand-700 dark:text-brand-300 font-medium text-[10px]">
                Trang {source.page}
              </span>
            )}
          </span>

          {/* Section title */}
          {source.section_title && (
            <span className="text-[11px] font-medium text-slate-800 dark:text-slate-200 mb-2 line-clamp-1 block">
              📍 {source.section_title}
            </span>
          )}

          {/* Quote */}
          {source.quote && (
            <span className="p-2 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200/60 dark:border-slate-700/50 mb-2 block">
              <span className="flex items-start gap-1.5 text-[11px] text-slate-600 dark:text-slate-300 italic line-clamp-3">
                <Quote className="w-3 h-3 text-slate-400 flex-shrink-0 mt-0.5" />
                <span>{source.quote}</span>
              </span>
            </span>
          )}

          {/* Footer: Rerank Score & Click instruction */}
          <span className="flex items-center justify-between text-[10px] text-slate-500 dark:text-slate-400 pt-1">
            {source.score !== null && source.score !== undefined ? (
              <span className="flex items-center gap-1.5">
                <ShieldCheck className="w-3 h-3 text-emerald-500" />
                <span>Độ tin cậy:</span>
                <span className="font-semibold text-emerald-600 dark:text-emerald-400 font-mono">
                  {formatScorePct(source.score)}
                </span>
              </span>
            ) : (
              <span />
            )}

            <span className="flex items-center gap-0.5 text-brand-600 dark:text-brand-400 font-medium hover:underline cursor-pointer">
              Mở Inspector <ExternalLink className="w-2.5 h-2.5" />
            </span>
          </span>
        </span>
      )}
    </span>
  );
};
