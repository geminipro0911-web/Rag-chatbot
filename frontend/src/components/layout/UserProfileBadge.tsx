import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../../services/apiClient';
import { ShieldCheck, User } from 'lucide-react';

export const UserProfileBadge: React.FC = () => {
  const { data: user, isLoading } = useQuery({
    queryKey: ['user-me'],
    queryFn: apiClient.getMe,
    staleTime: Infinity, // User identity is set by reverse proxy for the session
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-3 p-2 rounded-xl bg-slate-100/60 dark:bg-slate-800/40 animate-pulse">
        <div className="w-9 h-9 rounded-full bg-slate-200 dark:bg-slate-700" />
        <div className="space-y-1 flex-1">
          <div className="h-3.5 bg-slate-200 dark:bg-slate-700 rounded w-24" />
          <div className="h-2.5 bg-slate-200 dark:bg-slate-700 rounded w-16" />
        </div>
      </div>
    );
  }

  const fullName = user?.full_name || user?.user_id || 'Người dùng SSO';
  const department = user?.department_id || 'GENERAL';
  const role = user?.role || 'user';
  const isAdmin = user?.is_admin || false;

  // Extract initials
  const initials = fullName
    .split(' ')
    .filter(Boolean)
    .slice(-2)
    .map((w) => w[0].toUpperCase())
    .join('') || 'MB';

  return (
    <div className="flex items-center gap-2.5 p-2 rounded-xl bg-slate-100/80 dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-700/60">
      <div className="relative flex-shrink-0 flex items-center justify-center w-9 h-9 rounded-full bg-gradient-to-tr from-brand-600 to-indigo-500 text-white font-semibold text-xs shadow-sm shadow-brand-500/20">
        {initials}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <p className="text-xs font-semibold text-slate-800 dark:text-slate-100 truncate" title={fullName}>
            {fullName}
          </p>
          {isAdmin && (
            <span className="flex-shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 border border-indigo-400/30">
              <ShieldCheck className="w-2.5 h-2.5 mr-0.5" />
              ADMIN
            </span>
          )}
        </div>

        <div className="flex items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
          <span className="truncate" title={`Phòng ban: ${department}`}>
            {department}
          </span>
          <span>•</span>
          <span className="capitalize">{role}</span>
        </div>
      </div>
    </div>
  );
};
