import React, { useMemo, useState } from 'react';
import {
  Bot,
  Plus,
  MessageSquare,
  Database,
  Trash2,
  AlertCircle,
  Loader2,
  Calendar,
  X,
} from 'lucide-react';
import { ChatSessionDTO } from '../../types/api';
import { UserProfileBadge } from './UserProfileBadge';
import { ThemeToggle } from './ThemeToggle';
import { HealthBadge } from './HealthBadge';

interface Props {
  isOpen: boolean;
  sessions: ChatSessionDTO[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession: (id: string) => Promise<void>;
  onOpenVault: () => void;
  onCloseSidebarMobile: () => void;
}

export const Sidebar: React.FC<Props> = ({
  isOpen,
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  onOpenVault,
  onCloseSidebarMobile,
}) => {
  const [sessionToDelete, setSessionToDelete] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Group sessions by Today, Last 7 days, Older
  const groupedSessions = useMemo(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    const sevenDaysAgo = new Date();
    sevenDaysAgo.setDate(today.getDate() - 7);
    sevenDaysAgo.setHours(0, 0, 0, 0);

    const groups: {
      today: ChatSessionDTO[];
      last7Days: ChatSessionDTO[];
      older: ChatSessionDTO[];
    } = {
      today: [],
      last7Days: [],
      older: [],
    };

    sessions.forEach((s) => {
      const d = new Date(s.updated_at || s.created_at);
      if (d >= today) {
        groups.today.push(s);
      } else if (d >= sevenDaysAgo) {
        groups.last7Days.push(s);
      } else {
        groups.older.push(s);
      }
    });

    return groups;
  }, [sessions]);

  const handleDeleteConfirm = async () => {
    if (!sessionToDelete) return;
    try {
      setIsDeleting(true);
      await onDeleteSession(sessionToDelete);
    } finally {
      setIsDeleting(false);
      setSessionToDelete(null);
    }
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Mobile backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm lg:hidden"
        onClick={onCloseSidebarMobile}
      />

      <aside className="fixed inset-y-0 left-0 z-40 w-72 bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 flex flex-col transition-all duration-300">
        {/* Header: Logo & Branding */}
        <div className="p-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-10 h-10 rounded-2xl bg-gradient-to-tr from-brand-600 to-indigo-500 text-white flex items-center justify-center shadow-lg shadow-brand-500/20 flex-shrink-0">
              <Bot className="w-6 h-6" />
            </div>

            <div>
              <div className="flex items-center gap-1.5">
                <span className="font-extrabold text-base tracking-tight text-slate-900 dark:text-slate-100">
                  Mbot
                </span>
                <span className="px-1.5 py-0.2 rounded font-mono text-[9px] font-bold bg-brand-50 text-brand-700 dark:bg-brand-950/60 dark:text-brand-300 border border-brand-200 dark:border-brand-800">
                  LAN 100%
                </span>
              </div>
              <p className="text-[10px] text-slate-400 font-medium truncate max-w-[150px]">
                Trợ lý AI Doanh nghiệp
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={onCloseSidebarMobile}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 lg:hidden"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Health pulse in sidebar */}
        <div className="px-4 pt-3 pb-1">
          <HealthBadge />
        </div>

        {/* Action Button: + New Chat */}
        <div className="p-3">
          <button
            type="button"
            onClick={onNewChat}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl font-semibold text-xs text-white bg-brand-600 hover:bg-brand-700 shadow-md shadow-brand-500/20 hover:shadow-lg transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>Cuộc trò chuyện mới</span>
          </button>
        </div>

        {/* Nav tabs / Quick Action: Knowledge Vault */}
        <div className="px-3 pb-2">
          <button
            type="button"
            onClick={onOpenVault}
            className="w-full flex items-center justify-between p-2.5 rounded-xl text-xs font-semibold text-slate-700 dark:text-slate-300 bg-slate-100/80 hover:bg-slate-200/80 dark:bg-slate-800/60 dark:hover:bg-slate-800 border border-slate-200/80 dark:border-slate-700/60 transition-colors"
          >
            <span className="flex items-center gap-2">
              <Database className="w-4 h-4 text-brand-600 dark:text-brand-400" />
              <span>Kho Tri thức & Dữ liệu</span>
            </span>
            <span className="text-[10px] text-brand-600 font-mono">Vault →</span>
          </button>
        </div>

        {/* Chat Sessions History List */}
        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-4 text-xs">
          {sessions.length === 0 ? (
            <div className="text-center py-10 px-2 text-slate-400">
              <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-40" />
              <p className="font-medium text-[11px]">Chưa có phiên chat nào</p>
              <p className="text-[10px] mt-0.5">Nhấp nút phía trên để bắt đầu hỏi đáp</p>
            </div>
          ) : (
            <>
              {/* Today */}
              {groupedSessions.today.length > 0 && (
                <div className="space-y-1">
                  <span className="px-2 text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1">
                    <Calendar className="w-2.5 h-2.5" /> Hôm nay
                  </span>
                  {groupedSessions.today.map((s) => (
                    <SessionItem
                      key={s.id}
                      session={s}
                      isActive={activeSessionId === s.id}
                      onSelect={() => onSelectSession(s.id)}
                      onDelete={() => setSessionToDelete(s.id)}
                    />
                  ))}
                </div>
              )}

              {/* 7 Days Ago */}
              {groupedSessions.last7Days.length > 0 && (
                <div className="space-y-1">
                  <span className="px-2 text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1">
                    <Calendar className="w-2.5 h-2.5" /> 7 ngày qua
                  </span>
                  {groupedSessions.last7Days.map((s) => (
                    <SessionItem
                      key={s.id}
                      session={s}
                      isActive={activeSessionId === s.id}
                      onSelect={() => onSelectSession(s.id)}
                      onDelete={() => setSessionToDelete(s.id)}
                    />
                  ))}
                </div>
              )}

              {/* Older */}
              {groupedSessions.older.length > 0 && (
                <div className="space-y-1">
                  <span className="px-2 text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1">
                    <Calendar className="w-2.5 h-2.5" /> Cũ hơn
                  </span>
                  {groupedSessions.older.map((s) => (
                    <SessionItem
                      key={s.id}
                      session={s}
                      isActive={activeSessionId === s.id}
                      onSelect={() => onSelectSession(s.id)}
                      onDelete={() => setSessionToDelete(s.id)}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer: SSO Profile Badge & Theme Toggle */}
        <div className="p-3 border-t border-slate-200 dark:border-slate-800 space-y-2">
          <UserProfileBadge />
          <div className="flex items-center justify-between px-1">
            <span className="text-[11px] text-slate-400">Giao diện Sáng / Tối</span>
            <ThemeToggle />
          </div>
        </div>
      </aside>

      {/* Delete Session Confirmation Dialog */}
      {sessionToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="w-full max-w-sm p-5 bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-800 text-xs">
            <div className="flex items-center gap-2.5 text-rose-600 dark:text-rose-400 mb-2.5">
              <AlertCircle className="w-5 h-5 flex-shrink-0" />
              <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">
                Xóa cuộc trò chuyện?
              </h3>
            </div>

            <p className="text-slate-600 dark:text-slate-300 leading-relaxed mb-4">
              Toàn bộ nội dung trao đổi trong phiên này sẽ bị xóa khỏi lịch sử và không thể khôi phục.
            </p>

            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setSessionToDelete(null)}
                disabled={isDeleting}
                className="px-3 py-1.5 rounded-xl font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                Hủy bỏ
              </button>
              <button
                type="button"
                onClick={handleDeleteConfirm}
                disabled={isDeleting}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl font-semibold text-white bg-rose-600 hover:bg-rose-700 shadow-sm disabled:opacity-50"
              >
                {isDeleting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                Xóa
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

const SessionItem: React.FC<{
  session: ChatSessionDTO;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
}> = ({ session, isActive, onSelect, onDelete }) => {
  return (
    <div
      onClick={onSelect}
      className={`group relative flex items-center justify-between p-2.5 rounded-xl cursor-pointer transition-all select-none ${
        isActive
          ? 'bg-brand-50 dark:bg-brand-950/40 text-brand-900 dark:text-brand-200 font-semibold border border-brand-200/80 dark:border-brand-800/80 shadow-xs'
          : 'text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800/60 font-normal'
      }`}
    >
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <MessageSquare
          className={`w-3.5 h-3.5 flex-shrink-0 ${
            isActive ? 'text-brand-600 dark:text-brand-400' : 'text-slate-400'
          }`}
        />
        <span className="truncate text-xs">{session.title}</span>
      </div>

      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        className="opacity-0 group-hover:opacity-100 p-1 rounded-md text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-all ml-1"
        title="Xóa phiên hội thoại"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </div>
  );
};
