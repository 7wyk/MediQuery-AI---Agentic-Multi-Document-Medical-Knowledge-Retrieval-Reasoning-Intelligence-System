import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
    ArrowUpRight,
    Menu,
    PanelLeftOpen,
    Plus,
    Search,
    Trash2,
} from 'lucide-react';
import Shell, { BrandMark } from '../components/layout/Shell';
import Modal from '../components/ui/Modal';
import ConversationSidebar from '../components/chat/ConversationSidebar';
import ChatMessage, { ChatMessageData } from '../components/chat/ChatMessage';
import ChatComposer, { RagMode } from '../components/chat/ChatComposer';
import EvidenceDrawer from '../components/chat/EvidenceDrawer';
import ThinkingIndicator from '../components/chat/ThinkingIndicator';
import chatService, {
    Conversation,
    ConversationDetail,
    SourceCitation,
} from '../services/chat.service';
import documentsService from '../services/documents.service';

const SUGGESTIONS = [
    'Summarise my uploaded medical guidelines.',
    'Explain a clinical concept from my documents.',
    'Compare recommendations across documents.',
    'Find the evidence supporting a particular statement.',
];

const SIDEBAR_KEY = 'mediquery:chat:sidebar';

const toChatMessages = (detail: ConversationDetail): ChatMessageData[] => {
    const restored: ChatMessageData[] = [];
    detail.messages.forEach((message) => {
        const timestamp = new Date(message.timestamp);
        restored.push({
            id: `user-${message.id}`,
            role: 'user',
            content: message.question,
            timestamp,
        });
        if (message.answer) {
            restored.push({
                id: `assistant-${message.id}`,
                role: 'assistant',
                content: message.answer,
                sources: (message.sources as SourceCitation[] | null) ?? [],
                timestamp,
                mode: message.mode ?? undefined,
                evidenceStatus: message.evidence_status ?? undefined,
                insufficient: message.insufficient_evidence,
            });
        }
    });
    return restored;
};

const byUpdatedDesc = (a: Conversation, b: Conversation) =>
    new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();

const sortConversations = (conversations: Conversation[]) =>
    [...conversations].sort((a, b) => {
        if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
        return byUpdatedDesc(a, b);
    });

const ChatPage: React.FC = () => {
    const [searchParams, setSearchParams] = useSearchParams();
    const initialConversationRef = useRef(searchParams.get('c'));

    const [conversations, setConversations] = useState<Conversation[]>([]);
    const [conversationsLoading, setConversationsLoading] = useState(true);
    const [activeId, setActiveId] = useState<number | null>(null);
    const [messages, setMessages] = useState<ChatMessageData[]>([]);
    const [messagesLoading, setMessagesLoading] = useState(false);

    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [ragMode, setRagMode] = useState<RagMode>('agentic');
    const [allowWebSearch, setAllowWebSearch] = useState(false);
    const [search, setSearch] = useState('');
    const [notice, setNotice] = useState('');

    const [sidebarCollapsed, setSidebarCollapsed] = useState(
        () => window.localStorage.getItem(SIDEBAR_KEY) === 'collapsed'
    );
    const [drawerOpen, setDrawerOpen] = useState(false);
    const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);

    const [evidenceMessageId, setEvidenceMessageId] = useState<string | null>(null);
    const [evidenceIndex, setEvidenceIndex] = useState<number | null>(null);

    const activeIdRef = useRef<number | null>(null);
    const inFlightRef = useRef(false);
    const skipLoadRef = useRef<number | null>(null);
    const scrollRef = useRef<HTMLDivElement>(null);
    const endRef = useRef<HTMLDivElement>(null);
    const searchRef = useRef(search);

    useEffect(() => {
        activeIdRef.current = activeId;
    }, [activeId]);

    useEffect(() => {
        searchRef.current = search;
    }, [search]);

    const refreshConversations = useCallback(async () => {
        try {
            const response = await chatService.listConversations(searchRef.current);
            setConversations(sortConversations(response.conversations));
        } catch {
            /* the sidebar keeps its last known state */
        }
    }, []);

    // Initial load: conversations, then the thread to open.
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const response = await chatService.listConversations();
                if (cancelled) return;
                const list = sortConversations(response.conversations);
                setConversations(list);

                const requested = Number(initialConversationRef.current);
                if (requested && list.some((item) => item.id === requested)) {
                    setActiveId(requested);
                } else if (!initialConversationRef.current && list.length > 0) {
                    const mostRecent = [...list].sort(byUpdatedDesc)[0];
                    setActiveId(mostRecent.id);
                    setSearchParams({ c: String(mostRecent.id) }, { replace: true });
                }
            } catch {
                if (!cancelled) {
                    setNotice('Could not load your conversations. You can still start a new chat.');
                }
            } finally {
                if (!cancelled) setConversationsLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Load the messages of the active conversation.
    useEffect(() => {
        if (activeId === null) {
            setMessages([]);
            return;
        }
        if (skipLoadRef.current === activeId) {
            skipLoadRef.current = null;
            return;
        }
        let cancelled = false;
        setMessagesLoading(true);
        chatService
            .getConversation(activeId)
            .then((detail) => {
                if (!cancelled) setMessages(toChatMessages(detail));
            })
            .catch(() => {
                if (!cancelled) {
                    setMessages([]);
                    setNotice('Could not load this conversation.');
                }
            })
            .finally(() => {
                if (!cancelled) setMessagesLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [activeId]);

    // Debounced title search (server-side, titles only).
    useEffect(() => {
        const timer = window.setTimeout(() => {
            refreshConversations();
        }, 250);
        return () => window.clearTimeout(timer);
    }, [search, refreshConversations]);

    useEffect(() => {
        window.localStorage.setItem(SIDEBAR_KEY, sidebarCollapsed ? 'collapsed' : 'open');
    }, [sidebarCollapsed]);

    useEffect(() => {
        endRef.current?.scrollIntoView({ block: 'end' });
    }, [messages, loading, messagesLoading]);

    useEffect(() => {
        setEvidenceMessageId(null);
        setEvidenceIndex(null);
    }, [activeId]);

    const activeConversation = useMemo(
        () => conversations.find((conversation) => conversation.id === activeId) ?? null,
        [conversations, activeId]
    );

    const evidenceMessage = useMemo(
        () => messages.find((message) => message.id === evidenceMessageId) ?? null,
        [messages, evidenceMessageId]
    );

    const openEvidence = (message: ChatMessageData, index: number | null) => {
        setEvidenceMessageId(message.id);
        setEvidenceIndex(index);
    };

    const startNewChat = useCallback(() => {
        setActiveId(null);
        setMessages([]);
        setInput('');
        setNotice('');
        setEvidenceMessageId(null);
        setDrawerOpen(false);
        setSearchParams({}, { replace: true });
        window.setTimeout(() => document.getElementById('chat-input')?.focus(), 30);
    }, [setSearchParams]);

    const selectConversation = (conversation: Conversation) => {
        setActiveId(conversation.id);
        setSearchParams({ c: String(conversation.id) });
        setDrawerOpen(false);
        setEvidenceMessageId(null);
    };

    const send = useCallback(
        async (raw: string, options?: { appendUser?: boolean }) => {
            const question = raw.trim();
            if (!question || inFlightRef.current) return;

            inFlightRef.current = true;
            const appendUser = options?.appendUser ?? true;
            const requestConversationId = activeIdRef.current;
            const localUserId = `local-user-${Date.now()}`;

            if (appendUser) {
                setMessages((previous) => [
                    ...previous,
                    { id: localUserId, role: 'user', content: question, timestamp: new Date() },
                ]);
            }
            setInput('');
            setNotice('');
            setEvidenceMessageId(null);
            setLoading(true);

            try {
                const response = await chatService.query({
                    question,
                    mode: ragMode,
                    allow_web_search: allowWebSearch,
                    conversation_id: requestConversationId ?? undefined,
                });

                if (activeIdRef.current === requestConversationId) {
                    const assistant: ChatMessageData = {
                        id: `local-assistant-${Date.now()}`,
                        role: 'assistant',
                        content: response.answer,
                        sources: response.sources,
                        timestamp: new Date(),
                        mode: response.mode,
                        agentMetadata: response.agent_metadata,
                        evidenceStatus: response.evidence_status,
                        insufficient: response.insufficient_evidence,
                    };
                    setMessages((previous) => [...previous, assistant]);
                }

                if (
                    response.conversation_id &&
                    response.conversation_id !== requestConversationId
                ) {
                    skipLoadRef.current = response.conversation_id;
                    activeIdRef.current = response.conversation_id;
                    setActiveId(response.conversation_id);
                    setSearchParams({ c: String(response.conversation_id) }, { replace: true });
                }

                await refreshConversations();
            } catch (error: any) {
                if (activeIdRef.current === requestConversationId) {
                    setMessages((previous) => [
                        ...previous,
                        {
                            id: `local-error-${Date.now()}`,
                            role: 'assistant',
                            content:
                                error?.response?.data?.detail ||
                                'The assistant could not answer that question. Check that your documents are processed and the API is reachable, then try again.',
                            timestamp: new Date(),
                            error: true,
                            retryQuestion: question,
                        },
                    ]);
                }
            } finally {
                setLoading(false);
                inFlightRef.current = false;
            }
        },
        [allowWebSearch, ragMode, refreshConversations, setSearchParams]
    );

    const handleRetry = (message: ChatMessageData) => {
        if (!message.retryQuestion) return;
        setMessages((previous) => previous.filter((item) => item.id !== message.id));
        void send(message.retryQuestion, { appendUser: false });
    };

    const handleRename = (conversation: Conversation, title: string) => {
        void (async () => {
            try {
                const updated = await chatService.renameConversation(conversation.id, title);
                setConversations((previous) =>
                    sortConversations(
                        previous.map((item) =>
                            item.id === conversation.id ? { ...item, title: updated.title } : item
                        )
                    )
                );
            } catch (error: any) {
                setNotice(error?.response?.data?.detail || 'Could not rename that conversation.');
            }
        })();
    };

    const handleTogglePin = (conversation: Conversation) => {
        void (async () => {
            try {
                const updated = await chatService.setPinned(conversation.id, !conversation.is_pinned);
                setConversations((previous) =>
                    sortConversations(
                        previous.map((item) => (item.id === conversation.id ? updated : item))
                    )
                );
            } catch {
                setNotice('Could not update the pin for that conversation.');
            }
        })();
    };

    const handleDelete = async () => {
        const target = deleteTarget;
        if (!target) return;
        setDeleteTarget(null);
        try {
            await chatService.deleteConversation(target.id);
            const remaining = conversations.filter((item) => item.id !== target.id);
            setConversations(remaining);
            if (activeId === target.id) {
                const next = [...remaining].sort(byUpdatedDesc)[0];
                if (next) {
                    setActiveId(next.id);
                    setSearchParams({ c: String(next.id) }, { replace: true });
                } else {
                    startNewChat();
                }
            }
        } catch {
            setNotice('Could not delete that conversation.');
        }
    };

    const openSourcePage = async (source: SourceCitation) => {
        if (source.kind === 'web' && source.url) {
            window.open(source.url, '_blank', 'noopener,noreferrer');
            return;
        }
        if (!source.document_id) {
            setNotice('This citation has no stored document to open.');
            return;
        }
        try {
            const { url } = await documentsService.getDownloadUrl(source.document_id);
            if (!url) {
                setNotice('The stored file for this citation is not available.');
                return;
            }
            const target = source.page ? `${url}#page=${source.page}` : url;
            window.open(target, '_blank', 'noopener,noreferrer');
        } catch {
            setNotice('Could not open the cited document.');
        }
    };

    const sidebarProps = {
        conversations,
        activeId,
        loading: conversationsLoading,
        search,
        onSearchChange: setSearch,
        onNewChat: startNewChat,
        onSelect: selectConversation,
        onRename: handleRename,
        onTogglePin: handleTogglePin,
        onDelete: (conversation: Conversation) => setDeleteTarget(conversation),
    };

    return (
        <Shell footer={false}>
            <div className="flex h-[calc(100vh-4rem)] overflow-hidden bg-white">
                {!sidebarCollapsed && (
                    <aside className="hidden w-[276px] shrink-0 border-r border-line bg-paper-wash/50 lg:flex">
                        <ConversationSidebar
                            {...sidebarProps}
                            onCollapse={() => setSidebarCollapsed(true)}
                        />
                    </aside>
                )}

                <section className="flex min-w-0 flex-1 flex-col">
                    <header className="flex h-[60px] shrink-0 items-center gap-2 border-b border-line bg-white px-3 sm:px-5">
                        <button
                            type="button"
                            onClick={() => setDrawerOpen(true)}
                            className="btn-icon lg:hidden"
                            aria-label="Open conversations"
                        >
                            <Menu className="h-4 w-4" strokeWidth={1.75} />
                        </button>

                        {sidebarCollapsed && (
                            <button
                                type="button"
                                onClick={() => setSidebarCollapsed(false)}
                                className="btn-icon hidden lg:inline-flex"
                                aria-label="Expand conversation list"
                            >
                                <PanelLeftOpen className="h-4 w-4" strokeWidth={1.75} />
                            </button>
                        )}

                        <div className="min-w-0 flex-1">
                            <h1 className="truncate text-[14.5px] font-medium tracking-tight text-ink">
                                {activeConversation?.title ?? 'New conversation'}
                            </h1>
                            <p className="mt-0.5 truncate text-[11.5px] text-ink-muted">
                                {ragMode === 'agentic'
                                    ? 'Agentic search across your documents'
                                    : 'Standard search across your documents'}
                            </p>
                        </div>

                        <button
                            type="button"
                            onClick={startNewChat}
                            className="btn-secondary btn-sm"
                        >
                            <Plus className="h-4 w-4" strokeWidth={2} />
                            <span className="hidden sm:inline">New chat</span>
                            <span className="sm:hidden">New</span>
                        </button>
                    </header>

                    <div ref={scrollRef} className="custom-scrollbar min-h-0 flex-1 overflow-y-auto">
                        <div className="mx-auto w-full max-w-[820px] px-4 py-6 sm:px-6">
                            {messagesLoading ? (
                                <div className="space-y-4">
                                    <div className="skeleton ml-auto h-10 w-2/3 max-w-sm" />
                                    <div className="skeleton h-24 w-full" />
                                    <div className="skeleton h-24 w-5/6" />
                                </div>
                            ) : messages.length === 0 ? (
                                <div className="py-6 sm:py-10">
                                    <BrandMark className="h-9 w-9 rounded-[10px]" />
                                    <h2 className="mt-4 text-[22px] font-medium tracking-tight text-ink">
                                        How can I help with your medical research?
                                    </h2>
                                    <p className="mt-1.5 max-w-lg text-[13.5px] leading-relaxed text-ink-soft">
                                        Ask questions about your uploaded guidelines, research papers and
                                        medical documents. Every answer cites the page it came from.
                                    </p>

                                    <div className="mt-6 grid gap-2 sm:grid-cols-2">
                                        {SUGGESTIONS.map((suggestion) => (
                                            <button
                                                key={suggestion}
                                                type="button"
                                                onClick={() => {
                                                    setInput(suggestion);
                                                    document.getElementById('chat-input')?.focus();
                                                }}
                                                className="group flex items-center justify-between gap-3 rounded-input border border-line bg-white px-3.5 py-3 text-left transition-colors duration-150 hover:border-sky-300"
                                            >
                                                <span className="text-[13px] leading-snug text-ink-soft">
                                                    {suggestion}
                                                </span>
                                                <ArrowUpRight
                                                    className="h-3.5 w-3.5 shrink-0 text-ink-muted transition-colors group-hover:text-royal"
                                                    strokeWidth={1.75}
                                                />
                                            </button>
                                        ))}
                                    </div>

                                    <p className="mt-6 flex items-center gap-1.5 text-[11.5px] text-ink-muted">
                                        <Search className="h-3 w-3" strokeWidth={1.75} />
                                        Answers are grounded in your own uploaded documents.
                                    </p>
                                </div>
                            ) : (
                                <div className="space-y-7">
                                    {messages.map((message) => (
                                        <ChatMessage
                                            key={message.id}
                                            message={message}
                                            activeSource={
                                                evidenceMessageId === message.id ? evidenceIndex : null
                                            }
                                            onSelectSource={
                                                message.sources?.length
                                                    ? (index) => openEvidence(message, index)
                                                    : undefined
                                            }
                                            onShowEvidence={() => openEvidence(message, null)}
                                            onRetry={() => handleRetry(message)}
                                        />
                                    ))}

                                    {loading && (
                                        <ThinkingIndicator
                                            mode={ragMode === 'agentic' ? 'agentic' : 'standard'}
                                        />
                                    )}
                                </div>
                            )}
                            <div ref={endRef} />
                        </div>
                    </div>

                    {notice && (
                        <div className="shrink-0 border-t border-line bg-white px-4 pt-3 sm:px-6">
                            <div className="alert-info mx-auto flex max-w-[820px] items-start justify-between gap-3">
                                <span>{notice}</span>
                                <button
                                    type="button"
                                    onClick={() => setNotice('')}
                                    className="shrink-0 text-[11.5px] font-medium underline"
                                >
                                    Dismiss
                                </button>
                            </div>
                        </div>
                    )}

                    <div className="shrink-0 border-t border-line bg-white">
                        <div className="mx-auto w-full max-w-[820px]">
                            <ChatComposer
                                value={input}
                                onChange={setInput}
                                onSubmit={() => void send(input)}
                                loading={loading}
                                disabled={messagesLoading}
                                mode={ragMode}
                                onModeChange={setRagMode}
                                allowWeb={allowWebSearch}
                                onAllowWebChange={setAllowWebSearch}
                            />
                        </div>
                    </div>
                </section>

                {drawerOpen && (
                    <div className="fixed inset-0 z-50 lg:hidden">
                        <div
                            className="absolute inset-0 animate-fade-in bg-ink/25"
                            onClick={() => setDrawerOpen(false)}
                            aria-hidden="true"
                        />
                        <div className="absolute inset-y-0 left-0 flex w-[86%] max-w-[320px] animate-fade-in flex-col border-r border-line bg-paper-wash">
                            <ConversationSidebar
                                {...sidebarProps}
                                onClose={() => setDrawerOpen(false)}
                            />
                        </div>
                    </div>
                )}
            </div>

            <EvidenceDrawer
                open={Boolean(evidenceMessage)}
                question={messages
                    .slice(0, messages.findIndex((message) => message.id === evidenceMessageId))
                    .filter((message) => message.role === 'user')
                    .slice(-1)[0]?.content}
                sources={evidenceMessage?.sources ?? []}
                activeIndex={evidenceIndex}
                onSelect={(index) => setEvidenceIndex((current) => (current === index ? null : index))}
                onOpen={openSourcePage}
                onClose={() => {
                    setEvidenceMessageId(null);
                    setEvidenceIndex(null);
                }}
            />

            <Modal
                open={Boolean(deleteTarget)}
                title="Delete this conversation?"
                description={
                    deleteTarget
                        ? `“${deleteTarget.title}” and all of its messages will be permanently deleted. Your uploaded documents are not affected.`
                        : undefined
                }
                onClose={() => setDeleteTarget(null)}
                footer={
                    <>
                        <button
                            type="button"
                            onClick={() => setDeleteTarget(null)}
                            className="btn-secondary btn-sm"
                        >
                            Keep conversation
                        </button>
                        <button
                            type="button"
                            onClick={() => void handleDelete()}
                            className="inline-flex h-9 items-center gap-1.5 rounded-btn bg-danger-ink px-3 text-[13px] font-medium text-white transition-colors hover:bg-danger"
                        >
                            <Trash2 className="h-4 w-4" strokeWidth={1.75} />
                            Delete
                        </button>
                    </>
                }
            />
        </Shell>
    );
};

export default ChatPage;
