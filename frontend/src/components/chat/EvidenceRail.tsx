import React from 'react';
import { ExternalLink, FileText, Globe } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { SourceCitation } from '../../services/chat.service';

interface EvidenceRailProps {
    sources: SourceCitation[];
    activeIndex?: number | null;
    onSelect?: (index: number) => void;
    onOpen?: (source: SourceCitation) => void;
    showHeader?: boolean;
    className?: string;
}

const relevancePercent = (score?: number | null) => {
    if (typeof score !== 'number') return null;
    return Math.max(0, Math.min(100, Math.round(score * 100)));
};

const SourceCard: React.FC<{
    source: SourceCitation;
    active: boolean;
    onSelect?: (index: number) => void;
    onOpen?: (source: SourceCitation) => void;
}> = ({ source, active, onSelect, onOpen }) => {
    const relevance = relevancePercent(source.score);
    const isWeb = source.kind === 'web';

    return (
        <li>
            <div
                className={cn(
                    'group rounded-input border bg-white p-3 transition-colors duration-150',
                    active ? 'border-royal' : 'border-line hover:border-sky-300'
                )}
            >
                <button
                    type="button"
                    onClick={() => onSelect?.(source.index)}
                    className="w-full text-left"
                    aria-pressed={active}
                >
                    <div className="flex items-start gap-2.5">
                        <span className={cn('ref mt-0.5 shrink-0', active && 'ref-active')}>
                            {source.index}
                        </span>
                        <div className="min-w-0 flex-1">
                            <p className="flex items-center gap-1.5 text-[12.5px] font-medium leading-snug text-ink">
                                {isWeb ? (
                                    <Globe className="h-3.5 w-3.5 shrink-0 text-ink-muted" strokeWidth={1.75} />
                                ) : (
                                    <FileText
                                        className="h-3.5 w-3.5 shrink-0 text-ink-muted"
                                        strokeWidth={1.75}
                                    />
                                )}
                                <span className="truncate">
                                    {isWeb ? source.title || 'External source' : source.filename}
                                </span>
                            </p>
                            <p className="meta mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
                                {!isWeb && source.page != null && <span>Page {source.page}</span>}
                                {!isWeb && wLabel(source.content_type)}
                                {isWeb && source.publisher && <span>{source.publisher}</span>}
                                {isWeb && <span>Web</span>}
                            </p>
                            <p className="clamp-3 mt-1.5 text-[12px] leading-relaxed text-ink-soft">
                                {source.snippet}
                            </p>
                        </div>
                    </div>
                </button>

                {(relevance !== null || (!isWeb && onOpen) || (isWeb && source.url)) && (
                    <div className="mt-2.5 flex items-center justify-between gap-3 border-t border-line pt-2">
                        {relevance !== null ? (
                            <span className="flex items-center gap-2">
                                <span className="h-1 w-16 overflow-hidden rounded-full bg-sky-100">
                                    <span
                                        className="block h-full rounded-full bg-royal/70"
                                        style={{ width: `${relevance}%` }}
                                    />
                                </span>
                                <span className="tabular text-[11px] text-ink-muted">
                                    {relevance}% match
                                </span>
                            </span>
                        ) : (
                            <span />
                        )}

                        {isWeb && source.url ? (
                            <a
                                href={source.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 text-[11.5px] font-medium text-royal hover:underline"
                            >
                                Open source
                                <ExternalLink className="h-3 w-3" />
                            </a>
                        ) : (
                            !isWeb &&
                            onOpen && (
                                <button
                                    type="button"
                                    onClick={() => onOpen(source)}
                                    className="inline-flex items-center gap-1 text-[11.5px] font-medium text-royal hover:underline"
                                >
                                    Open page
                                    <ExternalLink className="h-3 w-3" />
                                </button>
                            )
                        )}
                    </div>
                )}
            </div>
        </li>
    );
};

const wLabel = (type?: string | null) => {
    if (!type || type === 'text') return null;
    return <span className="capitalize">{type}</span>;
};

const EvidenceRail: React.FC<EvidenceRailProps> = ({
    sources,
    activeIndex,
    onSelect,
    onOpen,
    showHeader = true,
    className,
}) => {
    const documents = sources.filter((source) => source.kind !== 'web');
    const web = sources.filter((source) => source.kind === 'web');

    return (
        <aside className={cn('flex h-full flex-col', className)} aria-label="Cited evidence">
            {showHeader && (
                <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-3.5">
                    <div>
                        <span className="evidence-rule" aria-hidden="true" />
                        <h2 className="mt-1.5 text-[14px] font-medium text-ink">Cited evidence</h2>
                    </div>
                    <span className="tabular text-[12px] text-ink-muted">
                        {sources.length} source{sources.length === 1 ? '' : 's'}
                    </span>
                </div>
            )}

            <div className="custom-scrollbar flex-1 overflow-y-auto px-4 py-4">
                {sources.length === 0 ? (
                    <div className="rounded-input border border-dashed border-line px-4 py-6 text-center">
                        <FileText className="mx-auto h-5 w-5 text-ink-muted/70" strokeWidth={1.5} />
                        <p className="mt-2 text-[12.5px] font-medium text-ink-soft">No citations yet</p>
                        <p className="mt-1 text-[11.5px] leading-relaxed text-ink-muted">
                            Ask a question to see the passages behind each answer.
                        </p>
                    </div>
                ) : (
                    <div className="space-y-4">
                        {documents.length > 0 && (
                            <div>
                                <p className="mb-2 text-[11.5px] font-medium text-ink-muted">
                                    From your documents
                                </p>
                                <ul className="space-y-2">
                                    {documents.map((source) => (
                                        <SourceCard
                                            key={source.index}
                                            source={source}
                                            active={activeIndex === source.index}
                                            onSelect={onSelect}
                                            onOpen={onOpen}
                                        />
                                    ))}
                                </ul>
                            </div>
                        )}

                        {web.length > 0 && (
                            <div>
                                <p className="mb-2 text-[11.5px] font-medium text-ink-muted">
                                    External sources
                                </p>
                                <ul className="space-y-2">
                                    {web.map((source) => (
                                        <SourceCard
                                            key={source.index}
                                            source={source}
                                            active={activeIndex === source.index}
                                            onSelect={onSelect}
                                            onOpen={onOpen}
                                        />
                                    ))}
                                </ul>
                            </div>
                        )}
                    </div>
                )}
            </div>

            <p className="border-t border-line px-4 py-3 text-[11px] leading-relaxed text-ink-muted">
                Citations point to the page the passage was read from.
            </p>
        </aside>
    );
};

export default EvidenceRail;
