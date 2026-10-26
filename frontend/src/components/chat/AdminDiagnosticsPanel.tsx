import React, { useState } from 'react';
import { DebugInfo } from '../../types/api';
import {
  Terminal,
  ChevronDown,
  ChevronUp,
  Clock,
  Layers,
  Check,
  Copy,
  Code2,
} from 'lucide-react';

interface Props {
  debug?: DebugInfo | null;
}

export const AdminDiagnosticsPanel: React.FC<Props> = ({ debug }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!debug) return null;

  const handleCopyCode = async () => {
    if (!debug.code) return;
    try {
      await navigator.clipboard.writeText(debug.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="mt-3 rounded-2xl border border-indigo-200 dark:border-indigo-900/50 bg-indigo-50/40 dark:bg-indigo-950/20 overflow-hidden text-xs">
      {/* Accordion Toggle Header */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full p-3 flex items-center justify-between text-left hover:bg-indigo-100/50 dark:hover:bg-indigo-900/30 transition-colors select-none"
      >
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-indigo-600 dark:text-indigo-400 flex-shrink-0" />
          <span className="font-semibold text-indigo-950 dark:text-indigo-200">
            Admin Diagnostics & Truy Vấn Thực Thi
          </span>
          <span className="px-2 py-0.5 rounded-full font-mono text-[10px] font-bold uppercase bg-indigo-200/60 dark:bg-indigo-800/60 text-indigo-800 dark:text-indigo-200">
            {debug.language || 'SQL'}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {debug.latency_ms !== undefined && (
            <span className="flex items-center gap-1 font-mono text-[11px] text-slate-500 dark:text-slate-400">
              <Clock className="w-3 h-3 text-indigo-500" />
              {debug.latency_ms} ms
            </span>
          )}
          {isOpen ? (
            <ChevronUp className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
          )}
        </div>
      </button>

      {/* Accordion Content */}
      {isOpen && (
        <div className="p-3.5 border-t border-indigo-200/80 dark:border-indigo-900/50 space-y-3 bg-white/70 dark:bg-slate-900/70">
          {/* Rewritten Query */}
          <div>
            <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              Câu hỏi chuẩn hóa (Rewritten Query):
            </span>
            <p className="mt-1 font-medium text-slate-900 dark:text-slate-100 bg-slate-100/80 dark:bg-slate-800/80 p-2 rounded-xl">
              {debug.rewritten_query}
            </p>
          </div>

          {/* Metrics Row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 text-[11px]">
            <div className="p-2 rounded-xl bg-slate-100/60 dark:bg-slate-800/40 border border-slate-200/60 dark:border-slate-700/40">
              <span className="text-slate-500 block">Ngôn ngữ:</span>
              <span className="font-mono font-semibold text-slate-800 dark:text-slate-200 uppercase">
                {debug.language || 'DuckDB SQL'}
              </span>
            </div>

            <div className="p-2 rounded-xl bg-slate-100/60 dark:bg-slate-800/40 border border-slate-200/60 dark:border-slate-700/40">
              <span className="text-slate-500 block">Số lần thử:</span>
              <span className="font-mono font-semibold text-slate-800 dark:text-slate-200">
                {debug.attempts || 1} lần
              </span>
            </div>

            <div className="p-2 rounded-xl bg-slate-100/60 dark:bg-slate-800/40 border border-slate-200/60 dark:border-slate-700/40">
              <span className="text-slate-500 block">Độ trễ xử lý:</span>
              <span className="font-mono font-semibold text-slate-800 dark:text-slate-200">
                {debug.latency_ms || 0} ms
              </span>
            </div>

            <div className="p-2 rounded-xl bg-slate-100/60 dark:bg-slate-800/40 border border-slate-200/60 dark:border-slate-700/40">
              <span className="text-slate-500 block">Rerank Scores:</span>
              <span className="font-mono font-semibold text-slate-800 dark:text-slate-200 truncate block">
                {debug.rerank_scores && debug.rerank_scores.length > 0
                  ? debug.rerank_scores.map((s) => s.toFixed(2)).join(', ')
                  : 'N/A'}
              </span>
            </div>
          </div>

          {/* Executed Code Box */}
          {debug.code && (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider flex items-center gap-1">
                  <Code2 className="w-3.5 h-3.5" /> Mã lệnh thực thi trong Sandbox:
                </span>

                <button
                  type="button"
                  onClick={handleCopyCode}
                  className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[11px] font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-800 transition-colors"
                >
                  {copied ? (
                    <>
                      <Check className="w-3 h-3 text-emerald-500" />
                      <span className="text-emerald-600 dark:text-emerald-400">Đã chép</span>
                    </>
                  ) : (
                    <>
                      <Copy className="w-3 h-3" />
                      <span>Sao chép mã</span>
                    </>
                  )}
                </button>
              </div>

              <div className="p-3 rounded-xl bg-slate-950 text-slate-200 font-mono text-[11px] overflow-x-auto leading-relaxed border border-slate-800">
                <pre>{debug.code}</pre>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
