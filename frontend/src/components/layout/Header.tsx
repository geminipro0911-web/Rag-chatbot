import React from 'react';
import { Menu, Globe, Lock, Database, Sparkles } from 'lucide-react';
import { HealthBadge } from './HealthBadge';

interface Props {
  title: string;
  isPublicOnly: boolean;
  onTogglePublicOnly: (val: boolean) => void;
  onOpenVault: () => void;
  onToggleSidebar: () => void;
}

export const Header: React.FC<Props> = ({
  title,
  isPublicOnly,
  onTogglePublicOnly,
  onOpenVault,
  onToggleSidebar,
}) => {
  return (
    <header className="h-14 px-4 bg-white/80 dark:bg-slate-950/80 backdrop-blur-md border-b border-slate-200 dark:border-slate-800 flex items-center justify-between gap-3 sticky top-0 z-30">
      {/* Left section: Hamburger + Title */}
      <div className="flex items-center gap-3 min-w-0">
        <button
          type="button"
          onClick={onToggleSidebar}
          className="p-1.5 rounded-xl text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          title="Đóng / Mở thanh bên"
        >
          <Menu className="w-5 h-5" />
        </button>

        <h1 className="text-sm font-bold text-slate-900 dark:text-slate-100 truncate flex items-center gap-2">
          <span>{title || 'Cuộc trò chuyện mới'}</span>
        </h1>
      </div>

      {/* Right section: Controls */}
      <div className="flex items-center gap-2 sm:gap-3">
        {/* Public only switch */}
        <div className="flex items-center gap-1.5 p-1 rounded-full bg-slate-100 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/80 text-xs">
          <button
            type="button"
            onClick={() => onTogglePublicOnly(!isPublicOnly)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full font-medium transition-all ${
              isPublicOnly
                ? 'bg-emerald-500 text-white shadow-xs'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
            }`}
            title="Khi bật, AI chỉ tìm kiếm dữ liệu trong các tài liệu công khai toàn công ty"
          >
            {isPublicOnly ? <Globe className="w-3.5 h-3.5" /> : <Lock className="w-3.5 h-3.5" />}
            <span className="hidden md:inline">
              {isPublicOnly ? 'Chỉ tìm công khai' : 'Phòng ban & Công khai'}
            </span>
          </button>
        </div>

        {/* Knowledge Vault quick button */}
        <button
          type="button"
          onClick={onOpenVault}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-brand-700 dark:text-brand-300 bg-brand-50 hover:bg-brand-100 dark:bg-brand-950/60 dark:hover:bg-brand-900/60 border border-brand-200/80 dark:border-brand-800/80 transition-all shadow-xs"
          title="Mở ngăn quản lý tệp và nạp dữ liệu"
        >
          <Database className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Kho Dữ liệu & Tải tệp</span>
        </button>

        {/* Real-time Health pulse */}
        <div className="hidden lg:block">
          <HealthBadge />
        </div>
      </div>
    </header>
  );
};
