import React, { useState, useRef, useEffect } from 'react';
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { apiClient } from './services/apiClient';
import { ChatMessageDTO } from './types/api';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { ChatContainer } from './components/chat/ChatContainer';
import { FileVaultDrawer } from './components/files/FileVaultDrawer';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 10000,
    },
  },
});

const MainDashboard: React.FC = () => {
  const qc = useQueryClient();
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const activeSessionRef = useRef<string | null>(activeSessionId);
  const [isPublicOnly, setIsPublicOnly] = useState<boolean>(false);
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true);
  const [fileVaultOpen, setFileVaultOpen] = useState<boolean>(false);
  const [isSending, setIsSending] = useState<boolean>(false);
  const [chatError, setChatError] = useState<string | null>(null);

  useEffect(() => {
    activeSessionRef.current = activeSessionId;
  }, [activeSessionId]);

  // Fetch list of sessions
  const { data: sessions = [] } = useQuery({
    queryKey: ['chat-sessions'],
    queryFn: apiClient.getSessions,
  });

  // Fetch messages of current active session
  const { data: messages = [], refetch: refetchMessages } = useQuery({
    queryKey: ['session-messages', activeSessionId],
    queryFn: () => (activeSessionId ? apiClient.getSessionMessages(activeSessionId) : Promise.resolve([])),
    enabled: !!activeSessionId,
  });

  // Active session title
  const currentSession = sessions.find((s) => s.id === activeSessionId);
  const sessionTitle = currentSession?.title || 'Cuộc trò chuyện mới';

  // Send message handler with race condition prevention
  const handleSendMessage = async (text: string) => {
    setChatError(null);
    const sentSessionId = activeSessionId;
    try {
      setIsSending(true);

      // Optimistic user message
      const tempUserMsgId = 'temp-' + Date.now();
      const optimisticUserMsg: ChatMessageDTO = {
        id: tempUserMsgId,
        session_id: sentSessionId || '',
        role: 'user',
        content: text,
        created_at: new Date().toISOString(),
      };

      // Set temporary state for snappy UI
      qc.setQueryData<ChatMessageDTO[]>(['session-messages', sentSessionId], (old = []) => [
        ...old,
        optimisticUserMsg,
      ]);

      const res = await apiClient.sendChatMessage({
        message: text,
        session_id: sentSessionId || undefined,
        is_public_only: isPublicOnly,
      });

      // Clear any temporary cache on null key
      if (!sentSessionId) {
        qc.setQueryData(['session-messages', null], []);
        qc.removeQueries({ queryKey: ['session-messages', null] });

        // Prime the cache for new session before switching activeSessionId
        const assistantMsg: ChatMessageDTO = {
          id: res.message_id,
          session_id: res.session_id,
          role: 'assistant',
          content: res.answer_markdown,
          route: res.route,
          sources: res.sources,
          tables: res.tables,
          debug: res.debug,
          created_at: new Date().toISOString(),
        };

        qc.setQueryData<ChatMessageDTO[]>(['session-messages', res.session_id], [
          optimisticUserMsg,
          assistantMsg,
        ]);

        // Only switch active session if user hasn't navigated to another conversation while waiting
        if (activeSessionRef.current === null) {
          setActiveSessionId(res.session_id);
        }
      }

      // Refresh sessions and messages
      await qc.invalidateQueries({ queryKey: ['chat-sessions'] });
      await qc.invalidateQueries({ queryKey: ['session-messages', res.session_id] });
    } catch (err: any) {
      console.error('Failed to send message:', err);
      // Clean up optimistic state on error
      if (!sentSessionId) {
        qc.setQueryData(['session-messages', null], []);
        qc.removeQueries({ queryKey: ['session-messages', null] });
      } else {
        await refetchMessages();
      }
      if (activeSessionRef.current === sentSessionId) {
        setChatError(err.message || 'Không thể gửi tin nhắn. Vui lòng thử lại.');
      }
    } finally {
      setIsSending(false);
    }
  };

  const handleNewChat = () => {
    // Explicitly reset any cached messages for null session
    qc.setQueryData(['session-messages', null], []);
    qc.removeQueries({ queryKey: ['session-messages', null] });
    setChatError(null);
    setActiveSessionId(null);
  };

  const handleDeleteSession = async (sessionId: string) => {
    await apiClient.deleteSession(sessionId);
    if (activeSessionId === sessionId) {
      handleNewChat();
    }
    await qc.invalidateQueries({ queryKey: ['chat-sessions'] });
  };

  const handleFeedbackSaved = (
    messageId: string,
    feedback: 'thumbs_up' | 'thumbs_down'
  ) => {
    qc.setQueryData<ChatMessageDTO[]>(
      ['session-messages', activeSessionId],
      (old = []) =>
        old.map((m) => (m.id === messageId ? { ...m, feedback } : m))
    );
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-50 dark:bg-slate-950 font-sans">
      {/* Collapsible Left Sidebar */}
      <Sidebar
        isOpen={sidebarOpen}
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={(id) => {
          setChatError(null);
          setActiveSessionId(id);
        }}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        onOpenVault={() => setFileVaultOpen(true)}
        onCloseSidebarMobile={() => setSidebarOpen(false)}
      />

      {/* Main Content Area */}
      <div
        className={`flex-1 flex flex-col h-full min-w-0 transition-all duration-300 ${
          sidebarOpen ? 'lg:pl-72' : 'pl-0'
        }`}
      >
        <Header
          title={sessionTitle}
          isPublicOnly={isPublicOnly}
          onTogglePublicOnly={setIsPublicOnly}
          onOpenVault={() => setFileVaultOpen(true)}
          onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
        />

        <main className="flex-1 flex flex-col h-[calc(100vh-3.5rem)] overflow-hidden">
          <ChatContainer
            messages={messages}
            isLoading={isSending}
            chatError={chatError}
            onDismissError={() => setChatError(null)}
            onSendMessage={handleSendMessage}
            onFeedbackSaved={handleFeedbackSaved}
          />
        </main>
      </div>

      {/* File Vault Slide-over Drawer */}
      <FileVaultDrawer
        isOpen={fileVaultOpen}
        onClose={() => setFileVaultOpen(false)}
      />
    </div>
  );
};

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <MainDashboard />
    </QueryClientProvider>
  );
}
