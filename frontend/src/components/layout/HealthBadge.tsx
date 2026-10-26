import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../../services/apiClient';
import { Activity, Database, Server } from 'lucide-react';

export const HealthBadge: React.FC = () => {
  const [showTooltip, setShowTooltip] = useState(false);

  const { data: health, isError } = useQuery({
    queryKey: ['system-health'],
    queryFn: apiClient.getHealth,
    refetchInterval: 30000, // Check every 30 seconds
    retry: 1,
  });

  const status = isError ? 'unhealthy' : health?.status || 'degraded';

  const dotColor =
    status === 'healthy'
      ? 'bg-emerald-500 shadow-emerald-500/50'
      : status === 'degraded'
      ? 'bg-amber-500 shadow-amber-500/50'
      : 'bg-rose-500 shadow-rose-500/50';

  const label =
    status === 'healthy'
      ? 'Hệ thống Sẵn sàng'
      : status === 'degraded'
      ? 'Hiệu năng Giảm tải'
      : 'Mất kết nối Dịch vụ';

  return (
    <div className="relative inline-flex items-center">
      <button
        type="button"
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        onClick={() => setShowTooltip((prev) => !prev)}
        className="flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 hover:bg-slate-200 dark:bg-slate-800/80 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700/60 transition-all cursor-pointer"
      >
        <span className="relative flex h-2 w-2">
          {status === 'healthy' && (
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
          )}
          <span className={`relative inline-flex rounded-full h-2 w-2 ${dotColor}`}></span>
        </span>
        <span className="truncate max-w-[120px]">{label}</span>
      </button>

      {showTooltip && (
        <div className="absolute top-8 left-0 z-50 w-64 p-3 bg-white dark:bg-slate-900 rounded-xl shadow-xl border border-slate-200 dark:border-slate-800 text-xs text-slate-700 dark:text-slate-300 animate-in fade-in-50 zoom-in-95 duration-150">
          <div className="font-semibold text-slate-900 dark:text-slate-100 pb-2 mb-2 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
            <span className="flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5 text-brand-500" />
              Trạng thái Hạ tầng Mbot
            </span>
            <span className="capitalize font-mono text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800">
              {health?.app_env || 'offline'}
            </span>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-slate-500 dark:text-slate-400">
                <Database className="w-3.5 h-3.5" />
                PostgreSQL 16:
              </span>
              <span
                className={`font-semibold ${
                  health?.database === 'connected' ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-500'
                }`}
              >
                {health?.database || 'disconnected'}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-slate-500 dark:text-slate-400">
                <Server className="w-3.5 h-3.5" />
                Qdrant Vector:
              </span>
              <span
                className={`font-semibold ${
                  health?.vector_store === 'ready' ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-500'
                }`}
              >
                {health?.vector_store || 'unavailable'}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
