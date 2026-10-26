import React, { useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, User, Copy, Check } from 'lucide-react';
import { ChatMessageDTO, SourceCitation, TableResultDTO } from '../../types/api';
import { RouteBadge } from './RouteBadge';
import { CitationBadge } from './CitationBadge';
import { SmartTableRenderer } from './SmartTableRenderer';
import { AdminDiagnosticsPanel } from './AdminDiagnosticsPanel';
import { FeedbackModal } from './FeedbackModal';

interface Props {
  message: ChatMessageDTO;
  onOpenCitation: (index: number, sources: SourceCitation[]) => void;
  onFeedbackSaved: (messageId: string, feedback: 'thumbs_up' | 'thumbs_down') => void;
}

export const MessageBubble: React.FC<Props> = ({
  message,
  onOpenCitation,
  onFeedbackSaved,
}) => {
  const isUser = message.role === 'user';
  const [copied, setCopied] = useState(false);

  const handleCopyAnswer = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      console.error(e);
    }
  };

  // Helper to render text with interactive citations
  const renderTextWithCitations = (text: string) => {
    if (!text || isUser) return text;

    const parts: (string | JSX.Element)[] = [];
    const regex = /\[(\d+)\]/g;
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        parts.push(text.substring(lastIndex, match.index));
      }

      const citationIdx = parseInt(match[1], 10);
      const sourceObj = message.sources?.find((s) => s.index === citationIdx);

      parts.push(
        <CitationBadge
          key={`cit-${match.index}-${citationIdx}`}
          index={citationIdx}
          source={sourceObj}
          onClick={(idx) => onOpenCitation(idx, message.sources || [])}
        />
      );

      lastIndex = regex.lastIndex;
    }

    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex));
    }

    return parts;
  };

  // Recursive helper to transform strings inside JSX elements (strong, em, p, li, td, etc.)
  const renderNodesWithCitations = (node: React.ReactNode): React.ReactNode => {
    if (!node) return node;

    if (typeof node === 'string') {
      return renderTextWithCitations(node);
    }

    if (Array.isArray(node)) {
      return React.Children.map(node, (child) => renderNodesWithCitations(child));
    }

    if (React.isValidElement(node)) {
      // Don't transform inside <code> or <pre>
      if (node.type === 'code' || node.type === 'pre') {
        return node;
      }

      const { children, ...restProps } = node.props as any;
      if (children !== undefined) {
        return React.cloneElement(node, {
          ...restProps,
          children: renderNodesWithCitations(children),
        });
      }
    }

    return node;
  };

  // Custom table component for react-markdown
  const customMarkdownComponents = useMemo(() => {
    return {
      // Intercept elements to insert CitationBadges recursively
      p: ({ children }: any) => {
        return (
          <p className="mb-2 leading-relaxed">
            {renderNodesWithCitations(children)}
          </p>
        );
      },
      li: ({ children }: any) => {
        return (
          <li className="leading-relaxed">
            {renderNodesWithCitations(children)}
          </li>
        );
      },
      strong: ({ children, ...props }: any) => {
        return (
          <strong className="font-semibold text-slate-900 dark:text-slate-100" {...props}>
            {renderNodesWithCitations(children)}
          </strong>
        );
      },
      em: ({ children, ...props }: any) => {
        return (
          <em className="italic" {...props}>
            {renderNodesWithCitations(children)}
          </em>
        );
      },
      blockquote: ({ children, ...props }: any) => {
        return (
          <blockquote className="border-l-4 border-slate-300 dark:border-slate-700 pl-3 my-2 text-slate-600 dark:text-slate-400" {...props}>
            {renderNodesWithCitations(children)}
          </blockquote>
        );
      },
      td: ({ children, ...props }: any) => {
        return (
          <td className="px-3 py-1.5" {...props}>
            {renderNodesWithCitations(children)}
          </td>
        );
      },
      // Smart table renderer
      table: ({ node, ...props }: any) => {
        try {
          // Extract headers and rows from node children
          const thead = node?.children?.find((c: any) => c.tagName === 'thead');
          const tbody = node?.children?.find((c: any) => c.tagName === 'tbody');

          const headerRow = thead?.children?.find((c: any) => c.tagName === 'tr');
          const headers: string[] =
            headerRow?.children
              ?.filter((c: any) => c.tagName === 'th')
              .map((th: any) => {
                const getTxt = (n: any): string =>
                  n?.value || (n?.children ? n.children.map(getTxt).join('') : '');
                return getTxt(th).trim();
              }) || [];

          const rows: string[][] =
            tbody?.children
              ?.filter((c: any) => c.tagName === 'tr')
              .map((tr: any) =>
                tr?.children
                  ?.filter((c: any) => c.tagName === 'td')
                  .map((td: any) => {
                    const getTxt = (n: any): string =>
                      n?.value || (n?.children ? n.children.map(getTxt).join('') : '');
                    return getTxt(td).trim();
                  })
              ) || [];

          if (headers.length > 0 && rows.length > 0) {
            // Find matching TableResultDTO
            let matchedMeta: TableResultDTO | undefined = undefined;
            const isSummary =
              (headers[0] || '').toLowerCase().includes('thống kê') ||
              (headers[0] || '').toLowerCase().includes('chỉ số') ||
              (headers[0] || '').toLowerCase().includes('metric');

            if (!isSummary && message.tables && message.tables.length > 0) {
              matchedMeta = message.tables.find((t) => {
                const overlap = headers.filter((h) => t.columns.includes(h));
                return overlap.length > 0 && overlap.length >= Math.min(2, headers.length);
              }) || message.tables[0];
            }

            return <SmartTableRenderer headers={headers} rows={rows} meta={matchedMeta} />;
          }
        } catch (e) {
          console.warn('Fallback standard table:', e);
        }

        return (
          <div className="overflow-x-auto my-3">
            <table className="w-full text-xs divide-y divide-slate-200 dark:divide-slate-800" {...props} />
          </div>
        );
      },
      code: ({ inline, className, children, ...props }: any) => {
        const match = /language-(\w+)/.exec(className || '');
        if (!inline && match) {
          return (
            <div className="my-2 rounded-xl bg-slate-950 p-3 text-slate-100 font-mono text-xs overflow-x-auto border border-slate-800">
              <pre {...props}>
                <code>{children}</code>
              </pre>
            </div>
          );
        }
        return (
          <code
            className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono text-[11px] text-brand-600 dark:text-brand-300 font-semibold"
            {...props}
          >
            {children}
          </code>
        );
      },
    };
  }, [message.sources, message.tables]);

  if (isUser) {
    return (
      <div className="flex items-start justify-end gap-2.5 my-4 animate-in fade-in slide-in-from-bottom-2 duration-200">
        <div className="max-w-[85%] sm:max-w-[75%] rounded-3xl rounded-tr-sm bg-brand-600 text-white px-4 py-3 shadow-md shadow-brand-500/10">
          <p className="text-xs sm:text-sm whitespace-pre-wrap leading-relaxed">{message.content}</p>
        </div>
        <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-200 flex items-center justify-center flex-shrink-0 text-xs font-bold shadow-xs">
          <User className="w-4 h-4" />
        </div>
      </div>
    );
  }

  // Assistant Bubble
  const defaultSql = message.debug?.code;

  return (
    <div className="flex items-start gap-3 my-4 animate-in fade-in slide-in-from-bottom-2 duration-200">
      <div className="w-8 h-8 rounded-2xl bg-gradient-to-tr from-brand-600 to-indigo-500 text-white flex items-center justify-center flex-shrink-0 shadow-md shadow-brand-500/20">
        <Bot className="w-4 h-4" />
      </div>

      <div className="flex-1 min-w-0 max-w-[92%] sm:max-w-[88%]">
        {/* Route Badge */}
        {message.route && (
          <div className="mb-2">
            <RouteBadge route={message.route} />
          </div>
        )}

        {/* Content Box */}
        <div className="rounded-3xl rounded-tl-sm bg-white dark:bg-slate-900 border border-slate-200/90 dark:border-slate-800/90 p-4 shadow-sm text-xs sm:text-sm text-slate-800 dark:text-slate-200">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={customMarkdownComponents}>
            {message.content}
          </ReactMarkdown>

          {/* Admin Diagnostics Accordion */}
          {message.debug && <AdminDiagnosticsPanel debug={message.debug} />}

          {/* Action Row: Copy & Feedback */}
          <div className="flex items-center justify-between pt-2.5 mt-2 border-t border-slate-100 dark:border-slate-800/80 text-xs">
            <FeedbackModal
              messageId={message.id}
              initialFeedback={message.feedback}
              defaultSql={defaultSql}
              onFeedbackSaved={(fb) => onFeedbackSaved(message.id, fb)}
            />

            <button
              type="button"
              onClick={handleCopyAnswer}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-[11px]"
              title="Sao chép toàn bộ câu trả lời"
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
          </div>
        </div>
      </div>
    </div>
  );
};
