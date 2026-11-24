import React from 'react';
import { AlertTriangle, FileText, RotateCcw } from 'lucide-react';
import type { AgentMetadata, SourceCitation } from '../../services/chat.service';
import AnswerBody from './AnswerBody';
import AnswerProvenance from './AnswerProvenance';
import { BrandMark } from '../layout/Shell';

export interface ChatMessageData {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    sources?: SourceCitation[];
    timestamp: Date;
    mode?: string;
    agentMetadata?: AgentMetadata | null;
    evidenceStatus?: string;
    insufficient?: boolean;
    error?: boolean;
    retryQuestion?: string;
}

interface ChatMessageProps {
    message: ChatMessageData;
    activeSource?: number | null;
    onSelectSource?: (index: number) => void;
    onShowEvidence?: () => void;
    onRetry?: () => void;
}

const timeLabel = (date: Date) =>
    date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

const ChatMessage: React.FC<ChatMessageProps> = ({
    message,
    activeSource,
    onSelectSource,
    onShowEvidence,
    onRetry,
}) => {
    if (message.role === 'user') {
        return (
            <div className="flex justify-end">
                <div className="max-w-[85%] sm:max-w-[32rem]">
                    <div className="rounded-[16px] rounded-br-[6px] border border-sky-200 bg-sky-100/80 px-4 py-2.5 text-[14px] leading-relaxed text-ink">
                        <p className="whitespace-pre-wrap break-words">{message.content}</p>
                    </div>
                    <p className="mt-1 pr-1 text-right text-[11px] text-ink-muted">
                        {timeLabel(message.timestamp)}
                    </p>
                </div>
            </div>
        );
    }

    if (message.error) {
        return (
            <div className="rounded-card border border-danger/25 bg-danger-soft/50 px-4 py-3.5">
                <div className="flex items-start gap-2.5">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger-ink" strokeWidth={1.75} />
                    <div className="min-w-0">
                        <p className="text-[13px] font-medium text-danger-ink">
                            The assistant could not answer
                        </p>
                        <p className="mt-1 text-[13px] leading-relaxed text-ink-soft">
                            {message.content}
                        </p>
                        {message.retryQuestion && onRetry && (
                            <button
                                type="button"
                                onClick={onRetry}
                                className="mt-2.5 inline-flex items-center gap-1.5 text-[12.5px] font-medium text-royal hover:underline"
                            >
                                <RotateCcw className="h-3.5 w-3.5" strokeWidth={1.75} />
                                Try again
                            </button>
                        )}
                    </div>
                </div>
            </div>
        );
    }

    const sources = message.sources ?? [];
    const isAgentic = message.mode === 'agentic';

    return (
        <article>
            <header className="mb-2 flex items-center gap-2">
                <BrandMark className="h-6 w-6 rounded-[7px] [&>svg]:h-3.5 [&>svg]:w-3.5" />
                <span className="text-[12.5px] font-medium text-ink">MediQuery AI</span>
                <span className="tabular text-[11px] text-ink-muted">{timeLabel(message.timestamp)}</span>
                {message.mode && (
                    <span className="ml-auto text-[11px] text-ink-muted">
                        {isAgentic ? 'Agentic search' : 'Standard search'}
                    </span>
                )}
            </header>

            {message.insufficient && (
                <div className="alert-warning mb-3 flex items-start gap-2">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
                    <span>
                        {message.evidenceStatus === 'rejected_domain'
                            ? 'This question falls outside the medical domain, so no documents were searched.'
                            : 'The evidence was not strong enough for a grounded answer, so the assistant abstained rather than guess.'}
                    </span>
                </div>
            )}

            <AnswerBody
                content={message.content}
                sources={sources}
                activeIndex={activeSource}
                onSelectSource={onSelectSource}
            />

            {(sources.length > 0 || (message.agentMetadata?.steps?.length ?? 0) > 0) && (
                <div className="mt-3.5 flex flex-wrap items-center gap-x-4 gap-y-2">
                    {sources.length > 0 && (
                        <button
                            type="button"
                            onClick={onShowEvidence}
                            className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-royal transition-colors hover:text-royal-hover hover:underline"
                        >
                            <FileText className="h-3.5 w-3.5" strokeWidth={1.75} />
                            View sources ({sources.length})
                        </button>
                    )}
                    {message.agentMetadata?.steps?.length ? (
                        <AnswerProvenance metadata={message.agentMetadata} />
                    ) : null}
                </div>
            )}
        </article>
    );
};

export default ChatMessage;
