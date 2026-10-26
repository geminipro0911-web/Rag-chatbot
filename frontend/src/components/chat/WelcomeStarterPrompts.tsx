import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../../services/apiClient';
import {
  Sparkles,
  Table2,
  FileText,
  Zap,
  ArrowRight,
  Bot,
} from 'lucide-react';

interface Props {
  onSelectPrompt: (promptText: string) => void;
}

export const WelcomeStarterPrompts: React.FC<Props> = ({ onSelectPrompt }) => {
  const { data: files = [] } = useQuery({
    queryKey: ['files-vault'],
    queryFn: () => apiClient.getFiles(),
    staleTime: 60000,
  });

  // Extract sheet names and document titles
  const sheetNames: string[] = [];
  const docTitles: string[] = [];

  files.forEach((f) => {
    if (f.tables_catalog && f.tables_catalog.length > 0) {
      f.tables_catalog.forEach((t) => sheetNames.push(t.sheet_name));
    }
    if (f.documents && f.documents.length > 0) {
      f.documents.forEach((d) => docTitles.push(d.title || f.file_name));
    }
  });

  const firstSheet = sheetNames[0] || 'Báo cáo Doanh thu';
  const firstDoc = docTitles[0] || 'Quy chế Tài chính';

  const starterCards = [
    {
      category: 'TABULAR',
      icon: Table2,
      badgeColor: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300 border-emerald-200/60 dark:border-emerald-800/40',
      title: 'Tra cứu số liệu Bảng tính',
      prompt: `Tổng hợp và tính tổng số liệu theo từng danh mục trong bảng ${firstSheet}?`,
      desc: 'Tính toán, nhóm và lọc số liệu DuckDB SQL tốc độ cao',
    },
    {
      category: 'TABULAR',
      icon: Table2,
      badgeColor: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300 border-emerald-200/60 dark:border-emerald-800/40',
      title: 'Top số liệu dẫn đầu',
      prompt: `Top 5 bản ghi có giá trị cao nhất trong ${firstSheet} là gì?`,
      desc: 'Sắp xếp, lọc thứ hạng và trực quan hóa biểu đồ',
    },
    {
      category: 'DOCUMENT',
      icon: FileText,
      badgeColor: 'bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300 border-blue-200/60 dark:border-blue-800/40',
      title: 'Tra cứu Văn bản & Quy chế',
      prompt: `Quy định và điều kiện áp dụng theo văn bản ${firstDoc} như thế nào?`,
      desc: 'Trích xuất chính xác kèm số trang và căn cứ pháp lý [1]',
    },
    {
      category: 'DOCUMENT',
      icon: FileText,
      badgeColor: 'bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300 border-blue-200/60 dark:border-blue-800/40',
      title: 'Tóm tắt điều khoản chính',
      prompt: `Tóm tắt các điểm quan trọng nhất trong tài liệu ${firstDoc}?`,
      desc: 'Rút trích các ý chính một cách ngắn gọn, súc tích',
    },
    {
      category: 'HYBRID',
      icon: Zap,
      badgeColor: 'bg-purple-50 text-purple-700 dark:bg-purple-950/50 dark:text-purple-300 border-purple-200/60 dark:border-purple-800/40',
      title: 'Truy vấn Kết hợp Đa nguồn',
      prompt: `Đối chiếu số liệu thực tế tại bảng ${firstSheet} với các điều khoản trong ${firstDoc}?`,
      desc: 'Phân tích chéo đa nguồn giữa văn bản quy định và bảng tính',
    },
    {
      category: 'HYBRID',
      icon: Zap,
      badgeColor: 'bg-purple-50 text-purple-700 dark:bg-purple-950/50 dark:text-purple-300 border-purple-200/60 dark:border-purple-800/40',
      title: 'Đánh giá & Khuyến nghị',
      prompt: `Phân tích hiệu quả và đề xuất giải pháp dựa trên dữ liệu ${firstSheet} và quy chế nội bộ?`,
      desc: 'Tổng hợp phân tích toàn diện phục vụ ra quyết định',
    },
  ];

  return (
    <div className="max-w-4xl mx-auto py-8 px-4 animate-in fade-in duration-300">
      {/* Banner */}
      <div className="text-center mb-8 space-y-3">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-3xl bg-gradient-to-tr from-brand-600 to-indigo-500 text-white shadow-xl shadow-brand-500/20 mb-1">
          <Bot className="w-8 h-8" />
        </div>

        <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
          Chào mừng bạn đến với <span className="text-brand-600 dark:text-brand-400">Mbot</span>
        </h1>

        <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 max-w-xl mx-auto leading-relaxed">
          Trợ lý AI Doanh nghiệp chuyên sâu Hỏi đáp Đa phương thức: Tính toán số liệu bảng tính Excel,
          trích dẫn tài liệu quy định nội bộ và phân tích dữ liệu đa nguồn an toàn 100% trong mạng LAN.
        </p>
      </div>

      {/* Starter Prompts Grid */}
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider px-1">
          <Sparkles className="w-3.5 h-3.5 text-brand-500" />
          <span>Gợi ý câu hỏi bắt đầu dựa trên tài liệu phòng ban:</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {starterCards.map((card, idx) => {
            const Icon = card.icon;

            return (
              <button
                key={idx}
                type="button"
                onClick={() => onSelectPrompt(card.prompt)}
                className="group p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 text-left hover:border-brand-400 dark:hover:border-brand-500 shadow-sm hover:shadow-md transition-all duration-200 flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${card.badgeColor}`}
                    >
                      <Icon className="w-3 h-3" />
                      {card.category}
                    </span>
                    <ArrowRight className="w-3.5 h-3.5 text-slate-300 dark:text-slate-600 group-hover:text-brand-500 group-hover:translate-x-1 transition-all" />
                  </div>

                  <h3 className="text-xs font-semibold text-slate-900 dark:text-slate-100 mb-1 line-clamp-1">
                    {card.title}
                  </h3>

                  <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed line-clamp-2">
                    "{card.prompt}"
                  </p>
                </div>

                <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-3 pt-2 border-t border-slate-100 dark:border-slate-800/80">
                  {card.desc}
                </p>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
};
