import React, { useEffect, useRef, useState } from 'react';
import { Send, Loader2, Sparkles, AlertCircle, X } from 'lucide-react';
import { ChatMessageDTO, SourceCitation } from '../../types/api';
import { MessageBubble } from './MessageBubble';
import { WelcomeStarterPrompts } from './WelcomeStarterPrompts';
import { SourceInspectorDrawer } from './SourceInspectorDrawer';

interface Props {
  messages: ChatMessageDTO[];
  isLoading: boolean;
  chatError?: string | null;
  onDismissError?: () => void;
  onSendMessage: (text: string) => Promise<void>;
  onFeedbackSaved: (messageId: string, feedback: 'thumbs_up' | 'thumbs_down') => void;
}

export const ChatContainer: React.FC<Props> = ({
  messages,
  isLoading,
  chatError,
  onDismissError,
  onSendMessage,
  onFeedbackSaved,
}) => {
  const [inputText, setInputText] = useState('');
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorSources, setInspectorSources] = useState<SourceCitation[]>([]);
  const [highlightCitationIndex, setHighlightCitationIndex] = useState<number | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom on new message or loading change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const handleOpenCitation = (index: number, sources: SourceCitation[]) => {
    setInspectorSources(sources);
    setHighlightCitationIndex(index);
    setInspectorOpen(true);
  };

  const handleSend = async () => {
    const text = inputText.trim();
    if (!text || isLoading) return;
    setInputText('');
    await onSendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSelectPrompt = (prompt: string) => {
    setInputText(prompt);
    textareaRef.current?.focus();
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-slate-50 dark:bg-slate-950">
      {/* Scrollable Chat Area */}
      <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-8">
        <div className="max-w-4xl mx-auto">
          {messages.length === 0 ? (
            <WelcomeStarterPrompts onSelectPrompt={handleSelectPrompt} />
          ) : (
            <div className="space-y-4">
              {messages.map((msg) => (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  onOpenCitation={handleOpenCitation}
                  onFeedbackSaved={onFeedbackSaved}
                />
              ))}

              {/* Multi-step loading stepper skeleton */}
              {isLoading && (
                <div className="flex items-start gap-3 my-4 animate-in fade-in duration-200">
                  <div className="w-8 h-8 rounded-2xl bg-gradient-to-tr from-brand-600 to-indigo-500 text-white flex items-center justify-center flex-shrink-0 shadow-md">
                    <Loader2 className="w-4 h-4 animate-spin" />
                  </div>

                  <div className="rounded-3xl rounded-tl-sm bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-4 shadow-sm space-y-2.5 max-w-sm sm:max-w-md">
                    <div className="flex items-center gap-2 text-xs font-semibold text-brand-600 dark:text-brand-400">
                      <Sparkles className="w-4 h-4 animate-pulse" />
                      <span>Mbot đang phân tích và xử lý truy vấn...</span>
                    </div>

                    <div className="space-y-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                      <div className="flex items-center gap-2">
                        <span className="w-1.5 h-1.5 rounded-full bg-brand-500 animate-ping" />
                        <span>Phân tích ý định & áp dụng phân quyền RBAC</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="w-1.5 h-1.5 rounded-full bg-slate-300 dark:bg-slate-700" />
                        <span>Truy vấn số liệu DuckDB / Trích xuất văn bản Qdrant</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          )}
        </div>
      </div>

      {/* Input bar */}
      <div className="p-4 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md border-t border-slate-200 dark:border-slate-800">
        <div className="max-w-4xl mx-auto">
          {/* Error Banner */}
          {chatError && (
            <div className="mb-2.5 p-3 rounded-2xl bg-rose-50 dark:bg-rose-950/40 border border-rose-300 dark:border-rose-900/60 flex items-center justify-between text-xs text-rose-700 dark:text-rose-300 animate-in fade-in slide-in-from-bottom-1 duration-150">
              <div className="flex items-center gap-2 min-w-0">
                <AlertCircle className="w-4 h-4 flex-shrink-0 text-rose-500" />
                <span className="truncate">{chatError}</span>
              </div>
              {onDismissError && (
                <button
                  type="button"
                  onClick={onDismissError}
                  className="p-1 rounded-lg hover:bg-rose-100 dark:hover:bg-rose-900/50 text-rose-500 transition-colors ml-2"
                  title="Đóng thông báo lỗi"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          )}

          <div className="relative rounded-2xl bg-slate-100 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/80 shadow-xs focus-within:border-brand-500 dark:focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-500/20 transition-all">
            <textarea
              ref={textareaRef}
              rows={2}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Đặt câu hỏi về bảng tính Excel hoặc tài liệu nội bộ... (Nhấn Enter để gửi, Shift+Enter xuống dòng)"
              className="w-full pl-4 pr-14 py-3 bg-transparent text-xs sm:text-sm text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none resize-none"
              disabled={isLoading}
            />

            <button
              type="button"
              onClick={handleSend}
              disabled={!inputText.trim() || isLoading}
              className="absolute right-2.5 bottom-2.5 p-2 rounded-xl bg-brand-600 hover:bg-brand-700 disabled:opacity-40 disabled:hover:bg-brand-600 text-white shadow-sm transition-all"
              title="Gửi câu hỏi"
            >
              {isLoading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
            </button>
          </div>

          <p className="text-[10px] text-center text-slate-400 dark:text-slate-500 mt-2">
            Mbot vận hành 100% Offline Air-Gapped trong mạng LAN nội bộ. Hãy kiểm tra các trích dẫn [n] để đối chiếu dữ liệu gốc.
          </p>
        </div>
      </div>

      {/* Source Inspector Drawer */}
      <SourceInspectorDrawer
        isOpen={inspectorOpen}
        sources={inspectorSources}
        highlightIndex={highlightCitationIndex}
        onClose={() => setInspectorOpen(false)}
      />
    </div>
  );
};
