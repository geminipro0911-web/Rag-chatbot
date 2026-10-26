import React from 'react';
import { ExecutionRoute } from '../../types/api';
import {
  Table2,
  FileText,
  Zap,
  HelpCircle,
  MessageSquare,
  Slash,
} from 'lucide-react';

interface Props {
  route?: ExecutionRoute | string | null;
}

export const RouteBadge: React.FC<Props> = ({ route }) => {
  if (!route) return null;

  switch (route) {
    case 'TABULAR':
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 border border-emerald-200/80 dark:border-emerald-800/40">
          <Table2 className="w-3.5 h-3.5" />
          Dữ liệu Bảng (TABULAR)
        </span>
      );
    case 'DOCUMENT':
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 border border-blue-200/80 dark:border-blue-800/40">
          <FileText className="w-3.5 h-3.5" />
          Tài liệu Văn bản (DOCUMENT)
        </span>
      );
    case 'HYBRID':
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-purple-50 text-purple-700 dark:bg-purple-950/40 dark:text-purple-300 border border-purple-200/80 dark:border-purple-800/40">
          <Zap className="w-3.5 h-3.5" />
          Kết hợp Đa nguồn (HYBRID)
        </span>
      );
    case 'CLARIFY':
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300 border border-amber-200/80 dark:border-amber-800/40">
          <HelpCircle className="w-3.5 h-3.5" />
          Cần làm rõ (CLARIFY)
        </span>
      );
    case 'CHITCHAT':
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
          <MessageSquare className="w-3.5 h-3.5" />
          Giao tiếp (CHITCHAT)
        </span>
      );
    case 'OUT_OF_SCOPE':
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 border border-rose-200/80 dark:border-rose-800/40">
          <Slash className="w-3.5 h-3.5" />
          Ngoài phạm vi (OUT_OF_SCOPE)
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
          {route}
        </span>
      );
  }
};
