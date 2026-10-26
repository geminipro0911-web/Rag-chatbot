import React, { useEffect, useMemo, useState } from 'react';
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { BarChart3, LineChart as LineIcon, PieChart as PieIcon } from 'lucide-react';
import { parseStrictNumber } from '../../utils/formatters';

interface Props {
  headers: string[];
  rows: (string | number | null | undefined)[][];
}

const COLORS = [
  '#4f46e5',
  '#06b6d4',
  '#10b981',
  '#f59e0b',
  '#ec4899',
  '#8b5cf6',
  '#3b82f6',
  '#14b8a6',
];

export const QuickChartView: React.FC<Props> = ({ headers, rows }) => {
  const [chartType, setChartType] = useState<'bar' | 'line' | 'pie'>('bar');

  // Find candidate numeric columns and string/category columns
  const columnAnalysis = useMemo(() => {
    const numericCols: number[] = [];
    const textCols: number[] = [];

    headers.forEach((_, colIdx) => {
      let numCount = 0;
      let nonNullCount = 0;

      rows.slice(0, 30).forEach((row) => {
        const val = row[colIdx];
        if (val !== null && val !== undefined && val !== '') {
          nonNullCount++;
          if (parseStrictNumber(val) !== null) {
            numCount++;
          }
        }
      });

      if (nonNullCount > 0 && numCount / nonNullCount >= 0.7) {
        numericCols.push(colIdx);
      } else {
        textCols.push(colIdx);
      }
    });

    return { numericCols, textCols };
  }, [headers, rows]);

  const [xAxisCol, setXAxisCol] = useState<number>(() => {
    return columnAnalysis.textCols[0] ?? 0;
  });

  const [yAxisCol, setYAxisCol] = useState<number>(() => {
    return columnAnalysis.numericCols[0] ?? (columnAnalysis.textCols[1] ?? 1);
  });

  // Keep X and Y synchronized when headers or analysis changes
  useEffect(() => {
    const defaultX = columnAnalysis.textCols[0] ?? 0;
    const defaultY =
      columnAnalysis.numericCols.find((col) => col !== defaultX) ??
      columnAnalysis.numericCols[0] ??
      (defaultX === 0 ? 1 : 0);

    setXAxisCol(defaultX);
    setYAxisCol(defaultY);
  }, [columnAnalysis]);

  // Prepare chart dataset
  const chartData = useMemo(() => {
    return rows.slice(0, 50).map((row) => {
      const xVal = row[xAxisCol] ?? 'N/A';
      const rawY = row[yAxisCol];
      const yVal = parseStrictNumber(rawY) ?? 0;
      return {
        name: String(xVal),
        value: yVal,
      };
    });
  }, [rows, xAxisCol, yAxisCol]);

  if (columnAnalysis.numericCols.length === 0) {
    return (
      <div className="p-8 text-center text-xs text-slate-500 dark:text-slate-400">
        Bảng dữ liệu không chứa cột số phù hợp để vẽ biểu đồ tự động.
      </div>
    );
  }

  const xLabel = headers[xAxisCol] || 'Trục X';
  const yLabel = headers[yAxisCol] || 'Trục Y';

  return (
    <div className="space-y-4 pt-2">
      {/* Chart toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-2.5 rounded-xl bg-slate-100/70 dark:bg-slate-800/50 border border-slate-200/80 dark:border-slate-700/60 text-xs">
        {/* Chart type switch */}
        <div className="flex items-center gap-1 bg-white dark:bg-slate-900 p-1 rounded-lg border border-slate-200 dark:border-slate-700">
          <button
            type="button"
            onClick={() => setChartType('bar')}
            className={`flex items-center gap-1 px-2.5 py-1 rounded font-medium transition-all ${
              chartType === 'bar'
                ? 'bg-brand-600 text-white shadow-xs'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" />
            Cột
          </button>
          <button
            type="button"
            onClick={() => setChartType('line')}
            className={`flex items-center gap-1 px-2.5 py-1 rounded font-medium transition-all ${
              chartType === 'line'
                ? 'bg-brand-600 text-white shadow-xs'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
            }`}
          >
            <LineIcon className="w-3.5 h-3.5" />
            Đường
          </button>
          <button
            type="button"
            onClick={() => setChartType('pie')}
            className={`flex items-center gap-1 px-2.5 py-1 rounded font-medium transition-all ${
              chartType === 'pie'
                ? 'bg-brand-600 text-white shadow-xs'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
            }`}
          >
            <PieIcon className="w-3.5 h-3.5" />
            Tròn
          </button>
        </div>

        {/* Axis selectors */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500 font-medium">Trục X:</span>
            <select
              value={xAxisCol}
              onChange={(e) => setXAxisCol(Number(e.target.value))}
              className="px-2 py-1 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 font-medium text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-brand-500"
            >
              {headers.map((h, i) => (
                <option key={i} value={i}>
                  {h}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-slate-500 font-medium">Trục Y:</span>
            <select
              value={yAxisCol}
              onChange={(e) => setYAxisCol(Number(e.target.value))}
              className="px-2 py-1 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 font-medium text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-brand-500"
            >
              {columnAnalysis.numericCols.map((colIdx) => (
                <option key={colIdx} value={colIdx}>
                  {headers[colIdx]}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Responsive Chart Container */}
      <div className="w-full h-72 sm:h-80 bg-white dark:bg-slate-900/60 p-3 rounded-2xl border border-slate-200/80 dark:border-slate-800">
        <ResponsiveContainer width="100%" height="100%">
          {chartType === 'bar' ? (
            <BarChart data={chartData} margin={{ top: 10, right: 20, left: 20, bottom: 25 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
              <XAxis
                dataKey="name"
                tick={{ fontSize: 11 }}
                interval={0}
                angle={-20}
                textAnchor="end"
              />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip
                formatter={(val: any) => [val.toLocaleString('vi-VN'), yLabel]}
                labelFormatter={(label) => `${xLabel}: ${label}`}
                contentStyle={{
                  backgroundColor: 'rgba(15, 23, 42, 0.9)',
                  borderRadius: '12px',
                  border: 'none',
                  color: '#fff',
                  fontSize: '12px',
                }}
              />
              <Legend verticalAlign="top" height={36} />
              <Bar dataKey="value" name={yLabel} fill="#4f46e5" radius={[6, 6, 0, 0]} />
            </BarChart>
          ) : chartType === 'line' ? (
            <LineChart data={chartData} margin={{ top: 10, right: 20, left: 20, bottom: 25 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
              <XAxis
                dataKey="name"
                tick={{ fontSize: 11 }}
                interval={0}
                angle={-20}
                textAnchor="end"
              />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip
                formatter={(val: any) => [val.toLocaleString('vi-VN'), yLabel]}
                labelFormatter={(label) => `${xLabel}: ${label}`}
                contentStyle={{
                  backgroundColor: 'rgba(15, 23, 42, 0.9)',
                  borderRadius: '12px',
                  border: 'none',
                  color: '#fff',
                  fontSize: '12px',
                }}
              />
              <Legend verticalAlign="top" height={36} />
              <Line
                type="monotone"
                dataKey="value"
                name={yLabel}
                stroke="#4f46e5"
                strokeWidth={2.5}
                dot={{ r: 4 }}
              />
            </LineChart>
          ) : (
            <PieChart>
              <Tooltip
                formatter={(val: any) => [val.toLocaleString('vi-VN'), yLabel]}
                contentStyle={{
                  backgroundColor: 'rgba(15, 23, 42, 0.9)',
                  borderRadius: '12px',
                  border: 'none',
                  color: '#fff',
                  fontSize: '12px',
                }}
              />
              <Legend />
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={90}
                label={({ name, percent }: any) =>
                  `${name} (${(percent * 100).toFixed(0)}%)`
                }
                labelLine={false}
              >
                {chartData.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
            </PieChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
};
