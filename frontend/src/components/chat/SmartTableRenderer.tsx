import React, { useMemo, useState } from 'react';
import {
  Table as TableIcon,
  BarChart2,
  Download,
  Copy,
  Check,
  Search,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from 'lucide-react';
import { exportTableToCsv, copyTableToClipboard } from '../../utils/exportCsv';
import { formatViNumber, parseStrictNumber, parseViDateTimestamp } from '../../utils/formatters';
import { QuickChartView } from './QuickChartView';
import { TableResultDTO } from '../../types/api';

interface Props {
  headers: string[];
  rows: (string | number | null | undefined)[][];
  meta?: TableResultDTO;
}

export const SmartTableRenderer: React.FC<Props> = ({ headers, rows, meta }) => {
  const [activeTab, setActiveTab] = useState<'table' | 'chart'>('table');
  const [searchQuery, setSearchQuery] = useState('');
  const [sortCol, setSortCol] = useState<number | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [copied, setCopied] = useState(false);

  // Handle column sorting
  const handleSort = (colIndex: number) => {
    if (sortCol === colIndex) {
      if (sortDir === 'asc') setSortDir('desc');
      else {
        setSortCol(null);
        setSortDir('asc');
      }
    } else {
      setSortCol(colIndex);
      setSortDir('asc');
    }
  };

  // Filter and Sort rows
  const processedRows = useMemo(() => {
    let result = [...rows];

    // Search query filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter((row) =>
        row.some((cell) => cell !== null && cell !== undefined && String(cell).toLowerCase().includes(q))
      );
    }

    // Sort
    if (sortCol !== null) {
      result.sort((a, b) => {
        const valA = a[sortCol];
        const valB = b[sortCol];

        if (valA === valB) return 0;
        if (valA === null || valA === undefined) return 1;
        if (valB === null || valB === undefined) return -1;

        // 1. Try Date sort (dd/mm/yyyy or ISO yyyy-mm-dd)
        const dateA = parseViDateTimestamp(valA);
        const dateB = parseViDateTimestamp(valB);
        if (dateA !== null && dateB !== null) {
          return sortDir === 'asc' ? dateA - dateB : dateB - dateA;
        }

        // 2. Try strict numeric sort
        const numA = parseStrictNumber(valA);
        const numB = parseStrictNumber(valB);
        if (numA !== null && numB !== null) {
          return sortDir === 'asc' ? numA - numB : numB - numA;
        }

        // 3. String sort
        const strA = String(valA);
        const strB = String(valB);
        return sortDir === 'asc'
          ? strA.localeCompare(strB, 'vi')
          : strB.localeCompare(strA, 'vi');
      });
    }

    return result;
  }, [rows, searchQuery, sortCol, sortDir]);

  const isSummaryTable = useMemo(() => {
    const firstHeader = (headers[0] || '').toLowerCase();
    return (
      firstHeader.includes('thống kê') ||
      firstHeader.includes('chỉ số') ||
      firstHeader.includes('metric') ||
      firstHeader.includes('statistic')
    );
  }, [headers]);

  const handleExportCsv = () => {
    const filename = isSummaryTable
      ? 'Bang_Thong_Ke_Tom_Tat'
      : meta?.sheet_name
      ? `${meta.file_name}_${meta.sheet_name}`
      : 'BaoCao_SoLieu';
    exportTableToCsv(filename, headers, processedRows);
  };

  const handleCopy = async () => {
    const ok = await copyTableToClipboard(headers, processedRows);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="my-4 rounded-2xl bg-slate-50/70 dark:bg-slate-900/70 border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
      {/* Table Toolbar */}
      <div className="p-3 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 flex flex-wrap items-center justify-between gap-3">
        {/* View Mode Switcher */}
        <div className="flex items-center gap-1 p-1 rounded-xl bg-slate-100 dark:bg-slate-800 text-xs font-semibold">
          <button
            type="button"
            onClick={() => setActiveTab('table')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-all ${
              activeTab === 'table'
                ? 'bg-white dark:bg-slate-900 text-brand-600 dark:text-brand-400 shadow-xs'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
            }`}
          >
            <TableIcon className="w-3.5 h-3.5" />
            Bảng dữ liệu
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('chart')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-all ${
              activeTab === 'chart'
                ? 'bg-white dark:bg-slate-900 text-brand-600 dark:text-brand-400 shadow-xs'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
            }`}
          >
            <BarChart2 className="w-3.5 h-3.5" />
            Biểu đồ trực quan
          </button>
        </div>

        {/* Search & Actions */}
        <div className="flex items-center gap-2">
          {activeTab === 'table' && (
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Lọc dòng..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-8 pr-3 py-1 text-xs rounded-xl bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-brand-500 w-32 sm:w-40"
              />
            </div>
          )}

          <button
            type="button"
            onClick={handleCopy}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-medium bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 transition-colors"
            title="Sao chép toàn bộ bảng vào Clipboard (dán trực tiếp vào Excel/Word)"
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-500" />
                <span className="text-emerald-600 dark:text-emerald-400">Đã chép</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                <span>Sao chép</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={handleExportCsv}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-medium bg-brand-50 hover:bg-brand-100 dark:bg-brand-950/60 dark:hover:bg-brand-900/60 text-brand-700 dark:text-brand-300 border border-brand-200/80 dark:border-brand-800/80 transition-colors"
            title="Tải tệp CSV (chuẩn UTF-8 BOM mở không bị lỗi font trên Excel Windows)"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Tải CSV</span>
          </button>
        </div>
      </div>

      {/* Main Body */}
      {activeTab === 'table' ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-700 dark:text-slate-300 divide-y divide-slate-200 dark:divide-slate-800">
            <thead className="bg-slate-100/80 dark:bg-slate-800/80 text-slate-800 dark:text-slate-200 font-semibold uppercase tracking-wider text-[11px]">
              <tr>
                {headers.map((h, idx) => {
                  const isSorted = sortCol === idx;
                  return (
                    <th
                      key={idx}
                      onClick={() => handleSort(idx)}
                      className="px-4 py-3 cursor-pointer hover:bg-slate-200/70 dark:hover:bg-slate-700/70 transition-colors select-none"
                    >
                      <div className="flex items-center gap-1.5">
                        <span className="truncate">{h}</span>
                        {isSorted ? (
                          sortDir === 'asc' ? (
                            <ArrowUp className="w-3 h-3 text-brand-600" />
                          ) : (
                            <ArrowDown className="w-3 h-3 text-brand-600" />
                          )
                        ) : (
                          <ArrowUpDown className="w-3 h-3 text-slate-400 opacity-60" />
                        )}
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800/60 bg-white dark:bg-slate-900 font-normal">
              {processedRows.length === 0 ? (
                <tr>
                  <td
                    colSpan={headers.length}
                    className="px-4 py-8 text-center text-slate-400 text-xs italic"
                  >
                    Không có hàng dữ liệu nào khớp với điều kiện lọc.
                  </td>
                </tr>
              ) : (
                processedRows.map((row, rIdx) => (
                  <tr
                    key={rIdx}
                    className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
                  >
                    {row.map((cell, cIdx) => (
                      <td key={cIdx} className="px-4 py-2.5 whitespace-nowrap font-mono text-[11px]">
                        {formatViNumber(cell)}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="p-4 bg-white dark:bg-slate-900">
          <QuickChartView headers={headers} rows={processedRows} />
        </div>
      )}

      {/* Footer Info Badge */}
      <div className="p-2.5 bg-slate-100/60 dark:bg-slate-800/40 border-t border-slate-200/80 dark:border-slate-800 flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400">
        <div>
          {isSummaryTable ? (
            <span>📊 Bảng thống kê tóm tắt các cột số</span>
          ) : meta?.file_name ? (
            <span>
              📊 Nguồn:{' '}
              <strong className="text-slate-700 dark:text-slate-300 font-semibold">
                {meta.file_name}
              </strong>{' '}
              {meta.sheet_name && `— Sheet: ${meta.sheet_name}`}
            </span>
          ) : (
            <span>📊 Kết quả bảng truy vấn tự động</span>
          )}
        </div>

        <div className="font-mono">
          {isSummaryTable ? (
            <span>Hiển thị {processedRows.length} chỉ số</span>
          ) : (
            <span>Hiển thị {processedRows.length} / {meta?.total_rows || rows.length} dòng</span>
          )}
        </div>
      </div>
    </div>
  );
};
