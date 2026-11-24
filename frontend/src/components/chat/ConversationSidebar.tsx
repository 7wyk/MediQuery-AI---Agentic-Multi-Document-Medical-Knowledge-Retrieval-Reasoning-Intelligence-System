import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    Lock,
    MessageSquare,
    MoreHorizontal,
    PanelLeftClose,
    Pencil,
    Pin,
    PinOff,
    Plus,
    Search,
    Trash2,
    X,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import type { Conversation } from '../../services/chat.service';
import { BrandMark } from '../layout/Shell';

const GROUP_ORDER = ['Pinned', 'Today', 'Yesterday', 'Previous 7 days', 'Previous 30 days', 'Older'];

const startOfDay = (date: Date) =>
    new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();

const daysSince = (value: string) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return Number.POSITIVE_INFINITY;
    return Math.round((startOfDay(new Date()) - startOfDay(date)) / 86_400_000);
};

const bucketFor = (conversation: Conversation): string => {
    if (conversation.is_pinned) return 'Pinned';
    const days = daysSince(conversation.updated_at);
    if (days <= 0) return 'Today';
    if (days === 1) return 'Yesterday';
    if (days <= 7) return 'Previous 7 days';
    if (days <= 30) return 'Previous 30 days';
    return 'Older';
};

export const groupConversations = (conversations: Conversation[]) => {
    const buckets = new Map<string, Conversation[]>();
    [...conversations]
        .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
        .forEach((conversation) => {
            const key = bucketFor(conversation);
            const bucket = buckets.get(key) ?? [];
            bucket.push(conversation);
            buckets.set(key, bucket);
        });

    return GROUP_ORDER.filter((label) => (buckets.get(label)?.length ?? 0) > 0).map((label) => ({
        label,
        items: buckets.get(label) ?? [],
    }));
};

interface ConversationSidebarProps {
    conversations: Conversation[];
    activeId: number | null;
    loading: boolean;
    search: string;
    onSearchChange: (value: string) => void;
    onNewChat: () => void;
    onSelect: (conversation: Conversation) => void;
    onRename: (conversation: Conversation, title: string) => void;
    onTogglePin: (conversation: Conversation) => void;
    onDelete: (conversation: Conversation) => void;
    onCollapse?: () => void;
    onClose?: () => void;
}

const ConversationSidebar: React.FC<ConversationSidebarProps> = ({
    conversations,
    activeId,
    loading,
    search,
    onSearchChange,
    onNewChat,
    onSelect,
    onRename,
    onTogglePin,
    onDelete,
    onCollapse,
    onClose,
}) => {
    const [menuId, setMenuId] = useState<number | null>(null);
    const [editingId, setEditingId] = useState<number | null>(null);
    const [draft, setDraft] = useState('');
    const [draftInvalid, setDraftInvalid] = useState(false);
    const cancelRename = useRef(false);
    const renameRef = useRef<HTMLInputElement>(null);
    const listRef = useRef<HTMLDivElement>(null);

    const groups = useMemo(() => groupConversations(conversations), [conversations]);

    useEffect(() => {
        if (editingId === null) return;
        renameRef.current?.focus();
        renameRef.current?.select();
    }, [editingId]);

    useEffect(() => {
        if (menuId === null) return;
        const close = (event: MouseEvent) => {
            if (!listRef.current?.contains(event.target as Node)) setMenuId(null);
        };
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') setMenuId(null);
        };
        document.addEventListener('mousedown', close);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', close);
            document.removeEventListener('keydown', onKey);
        };
    }, [menuId]);

    const beginRename = (conversation: Conversation) => {
        cancelRename.current = false;
        setMenuId(null);
        setDraftInvalid(false);
        setDraft(conversation.title);
        setEditingId(conversation.id);
    };

    const commitRename = (conversation: Conversation) => {
        if (cancelRename.current) {
            setEditingId(null);
            setDraftInvalid(false);
            return;
        }
        const title = draft.trim();
        if (!title) {
            // Empty titles are rejected rather than saved as a blank row.
            setDraftInvalid(true);
            renameRef.current?.focus();
            return;
        }
        setEditingId(null);
        setDraftInvalid(false);
        if (title !== conversation.title) onRename(conversation, title);
    };

    const renderRow = (conversation: Conversation) => {
        const active = conversation.id === activeId;
        const editing = editingId === conversation.id;

        return (
            <li key={conversation.id} className={cn('relative', editing && 'z-20')}>
                {editing ? (
                    <div>
                        <input
                            ref={renameRef}
                            value={draft}
                            onChange={(event) => {
                                setDraft(event.target.value);
                                setDraftInvalid(false);
                            }}
                            onKeyDown={(event) => {
                                if (event.key === 'Enter') {
                                    event.preventDefault();
                                    commitRename(conversation);
                                }
                                if (event.key === 'Escape') {
                                    event.preventDefault();
                                    cancelRename.current = true;
                                    setEditingId(null);
                                    setDraftInvalid(false);
                                }
                            }}
                            onBlur={() => {
                                if (!cancelRename.current) commitRename(conversation);
                            }}
                            aria-label="Conversation title"
                            aria-invalid={draftInvalid}
                            maxLength={200}
                            className={cn(
                                'h-8 w-full rounded-[8px] border bg-white px-2 text-[13px] text-ink focus:outline-none focus:ring-2 focus:ring-royal/15',
                                draftInvalid ? 'border-danger' : 'border-royal/40'
                            )}
                        />
                        {draftInvalid && (
                            <p className="mt-1 px-1 text-[11px] text-danger-ink">
                                Give the conversation a title.
                            </p>
                        )}
                    </div>
                ) : (
                    <div
                        className={cn(
                            'group/row flex items-center rounded-[9px] transition-colors duration-150',
                            active ? 'bg-royal-soft' : 'hover:bg-white'
                        )}
                    >
                        <button
                            type="button"
                            onClick={() => {
                                setMenuId(null);
                                onSelect(conversation);
                            }}
                            aria-current={active ? 'true' : undefined}
                            className="flex h-9 min-w-0 flex-1 items-center gap-2 pl-2.5 pr-1 text-left"
                        >
                            {conversation.is_pinned ? (
                                <Pin
                                    className="h-3 w-3 shrink-0 text-royal/70"
                                    strokeWidth={2}
                                    aria-label="Pinned"
                                />
                            ) : (
                                <MessageSquare
                                    className={cn(
                                        'h-3.5 w-3.5 shrink-0',
                                        active ? 'text-royal/70' : 'text-ink-muted/60'
                                    )}
                                    strokeWidth={1.75}
                                    aria-hidden="true"
                                />
                            )}
                            <span
                                className={cn(
                                    'truncate text-[13px] leading-none',
                                    active ? 'font-medium text-royal' : 'text-ink-soft'
                                )}
                                title={conversation.title}
                            >
                                {conversation.title}
                            </span>
                        </button>

                        <button
                            type="button"
                            onClick={() => setMenuId(menuId === conversation.id ? null : conversation.id)}
                            aria-label={`Actions for ${conversation.title}`}
                            aria-haspopup="menu"
                            aria-expanded={menuId === conversation.id}
                            className={cn(
                                'mr-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] text-ink-muted transition-opacity duration-150 hover:bg-white hover:text-ink focus-visible:opacity-100 max-lg:opacity-100',
                                menuId === conversation.id
                                    ? 'opacity-100'
                                    : 'opacity-0 group-hover/row:opacity-100'
                            )}
                        >
                            <MoreHorizontal className="h-4 w-4" strokeWidth={1.75} />
                        </button>
                    </div>
                )}

                {menuId === conversation.id && (
                    <div
                        role="menu"
                        className="absolute right-1 top-[34px] z-30 w-[168px] animate-fade-in rounded-input border border-line bg-white p-1 shadow-lift"
                    >
                        <button
                            type="button"
                            role="menuitem"
                            onClick={() => beginRename(conversation)}
                            className="flex w-full items-center gap-2 rounded-[7px] px-2.5 py-1.5 text-left text-[12.5px] text-ink-soft transition-colors hover:bg-paper-wash hover:text-ink"
                        >
                            <Pencil className="h-3.5 w-3.5" strokeWidth={1.75} />
                            Rename
                        </button>
                        <button
                            type="button"
                            role="menuitem"
                            onClick={() => {
                                setMenuId(null);
                                onTogglePin(conversation);
                            }}
                            className="flex w-full items-center gap-2 rounded-[7px] px-2.5 py-1.5 text-left text-[12.5px] text-ink-soft transition-colors hover:bg-paper-wash hover:text-ink"
                        >
                            {conversation.is_pinned ? (
                                <PinOff className="h-3.5 w-3.5" strokeWidth={1.75} />
                            ) : (
                                <Pin className="h-3.5 w-3.5" strokeWidth={1.75} />
                            )}
                            {conversation.is_pinned ? 'Unpin' : 'Pin'}
                        </button>
                        <button
                            type="button"
                            role="menuitem"
                            onClick={() => {
                                setMenuId(null);
                                onDelete(conversation);
                            }}
                            className="flex w-full items-center gap-2 rounded-[7px] px-2.5 py-1.5 text-left text-[12.5px] text-danger-ink transition-colors hover:bg-danger-soft"
                        >
                            <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
                            Delete
                        </button>
                    </div>
                )}
            </li>
        );
    };

    return (
        <div className="flex h-full min-h-0 w-full flex-col">
            <div className="flex items-center gap-2 px-3 pb-2 pt-3">
                <BrandMark className="h-7 w-7 rounded-[8px] [&>svg]:h-[15px] [&>svg]:w-[15px]" />
                <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium tracking-tight text-ink">
                    MediQuery AI
                </span>
                {onClose && (
                    <button type="button" onClick={onClose} className="btn-icon lg:hidden" aria-label="Close conversations">
                        <X className="h-4 w-4" />
                    </button>
                )}
                {onCollapse && (
                    <button
                        type="button"
                        onClick={onCollapse}
                        className="btn-icon hidden lg:inline-flex"
                        aria-label="Collapse conversation list"
                    >
                        <PanelLeftClose className="h-4 w-4" strokeWidth={1.75} />
                    </button>
                )}
            </div>

            <div className="px-3 pb-2">
                <button type="button" onClick={onNewChat} className="btn-secondary h-9 w-full justify-start px-2.5 text-[13px]">
                    <Plus className="h-4 w-4 text-royal" strokeWidth={2} />
                    New chat
                </button>
            </div>

            <div className="px-3 pb-2">
                <label htmlFor="conversation-search" className="sr-only">
                    Search conversations
                </label>
                <div className="relative">
                    <Search
                        className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted"
                        strokeWidth={1.75}
                    />
                    <input
                        id="conversation-search"
                        value={search}
                        onChange={(event) => onSearchChange(event.target.value)}
                        placeholder="Search conversations"
                        className="h-8 w-full rounded-[8px] border border-transparent bg-white/70 pl-8 pr-7 text-[12.5px] text-ink placeholder:text-ink-muted focus:border-sky-300 focus:bg-white focus:outline-none focus:ring-2 focus:ring-royal/10"
                    />
                    {search && (
                        <button
                            type="button"
                            onClick={() => onSearchChange('')}
                            className="absolute right-1.5 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded text-ink-muted hover:text-ink"
                            aria-label="Clear search"
                        >
                            <X className="h-3 w-3" />
                        </button>
                    )}
                </div>
            </div>

            <div ref={listRef} className="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-2 pb-3">
                {loading && conversations.length === 0 ? (
                    <div className="space-y-1.5 px-1 pt-2">
                        {[0, 1, 2, 3, 4].map((row) => (
                            <div key={row} className="skeleton h-9" />
                        ))}
                    </div>
                ) : groups.length === 0 ? (
                    <div className="px-2 pt-6 text-center">
                        <p className="text-[12.5px] font-medium text-ink-soft">
                            {search ? 'No matching conversations' : 'No conversations yet'}
                        </p>
                        <p className="mt-1 text-[11.5px] leading-relaxed text-ink-muted">
                            {search
                                ? 'Try a different title.'
                                : 'Your questions and answers will appear here.'}
                        </p>
                    </div>
                ) : (
                    groups.map((group) => (
                        <div key={group.label} className="mb-3">
                            <p className="px-2 pb-1 pt-2 text-[11.5px] font-medium text-ink-muted">
                                {group.label}
                            </p>
                            <ul className="space-y-0.5">{group.items.map(renderRow)}</ul>
                        </div>
                    ))
                )}
            </div>

            <div className="flex items-center gap-1.5 border-t border-line px-3 py-2.5 text-[11px] text-ink-muted">
                <Lock className="h-3 w-3 shrink-0" strokeWidth={1.75} />
                Only you can see these conversations
            </div>
        </div>
    );
};

export default ConversationSidebar;
