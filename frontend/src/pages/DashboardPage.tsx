import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, FileText, MessageSquare, Plus, Upload } from 'lucide-react';
import Shell from '../components/layout/Shell';
import PageHeader from '../components/layout/PageHeader';
import { Badge, EmptyState, Panel, PanelHeader, StatCard } from '../components/ui/Primitives';
import analyticsService, { UsageOverview } from '../services/analytics.service';
import documentsService, { Document } from '../services/documents.service';
import chatService, { ChatHistoryItem } from '../services/chat.service';
import { useAuth } from '../context/AuthContext';
import { documentStatusMeta } from '../lib/documentStatus';
import { formatFileSize, formatRelativeTime } from '../lib/utils';

const DashboardPage: React.FC = () => {
    const { user } = useAuth();
    const [overview, setOverview] = useState<UsageOverview | null>(null);
    const [documents, setDocuments] = useState<Document[]>([]);
    const [history, setHistory] = useState<ChatHistoryItem[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;

        const load = async () => {
            const [overviewResult, documentsResult, historyResult] = await Promise.allSettled([
                analyticsService.getOverview(),
                documentsService.list(),
                chatService.getHistory(5),
            ]);
            if (cancelled) return;

            if (overviewResult.status === 'fulfilled') setOverview(overviewResult.value);
            if (documentsResult.status === 'fulfilled') {
                setDocuments(documentsResult.value.documents ?? []);
            }
            if (historyResult.status === 'fulfilled') {
                setHistory(historyResult.value.history ?? []);
            }
            setLoading(false);
        };

        load();
        return () => {
            cancelled = true;
        };
    }, []);

    const indexState = useMemo(() => {
        return documents.reduce(
            (acc, doc) => {
                if (doc.status === 'completed') acc.indexed += 1;
                else if (doc.status === 'processing' || doc.status === 'queued') acc.pending += 1;
                else acc.attention += 1;
                return acc;
            },
            { indexed: 0, pending: 0, attention: 0 }
        );
    }, [documents]);

    const totalDocuments = overview?.total_documents ?? documents.length;
    const indexed = overview?.completed_documents ?? indexState.indexed;
    const indexedShare = totalDocuments > 0 ? Math.round((indexed / totalDocuments) * 100) : 0;
    const today = new Date().toLocaleDateString('en-GB', {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
    });

    const recentDocuments = [...documents]
        .sort((a, b) => new Date(b.upload_date).getTime() - new Date(a.upload_date).getTime())
        .slice(0, 4);

    return (
        <Shell>
            <PageHeader
                meta={today}
                title="Medical knowledge workspace"
                description={`Evidence-grounded answers for ${user?.full_name || 'your practice'}, drawn only from the documents you upload.`}
                actions={
                    <>
                        <Link to="/documents" className="btn-primary">
                            <Upload className="h-4 w-4" strokeWidth={1.75} />
                            Upload a document
                        </Link>
                        <Link to="/chat" className="btn-secondary">
                            <MessageSquare className="h-4 w-4" strokeWidth={1.75} />
                            Ask a question
                        </Link>
                    </>
                }
                aside={
                    <div className="panel hidden w-full border-sky-200/80 p-5 shadow-plate lg:block lg:w-[320px]">
                        <div className="flex items-start justify-between gap-3">
                            <div>
                                <p className="label">Knowledge base</p>
                                <p className="mt-1.5 text-[13px] text-ink-soft">
                                    {loading ? 'Reading index state' : `${indexed} of ${totalDocuments} documents indexed`}
                                </p>
                            </div>
                            <span className="tabular text-[19px] font-medium text-royal">{indexedShare}%</span>
                        </div>
                        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-sky-100">
                            <div
                                className="h-full rounded-full bg-royal transition-[width] duration-500"
                                style={{ width: `${indexedShare}%` }}
                            />
                        </div>
                        <dl className="mt-4 space-y-2 border-t border-line pt-3 text-[12.5px]">
                            <div className="flex items-center justify-between">
                                <dt className="text-ink-muted">Processing now</dt>
                                <dd className="tabular font-medium text-ink">
                                    {overview?.processing_documents ?? indexState.pending}
                                </dd>
                            </div>
                            <div className="flex items-center justify-between">
                                <dt className="text-ink-muted">Questions answered</dt>
                                <dd className="tabular font-medium text-ink">{overview?.total_queries ?? 0}</dd>
                            </div>
                            <div className="flex items-center justify-between">
                                <dt className="text-ink-muted">Answers that abstained</dt>
                                <dd className="tabular font-medium text-ink">
                                    {overview?.insufficient_evidence_queries ?? 0}
                                </dd>
                            </div>
                        </dl>
                    </div>
                }
            />

            <div className="mx-auto max-w-shell space-y-4 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
                <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <StatCard
                        label="Documents"
                        value={loading ? '—' : totalDocuments}
                        hint={`${indexed} indexed · ${indexState.pending} processing`}
                    />
                    <StatCard
                        label="Questions answered"
                        value={loading ? '—' : overview?.total_queries ?? 0}
                        hint={`${overview?.insufficient_evidence_queries ?? 0} abstained for weak evidence`}
                    />
                    <StatCard
                        label="Average response"
                        value={loading ? '—' : `${(overview?.avg_response_time ?? 0).toFixed(2)} s`}
                        hint="Both retrieval modes"
                    />
                    <StatCard
                        label="Estimated AI cost"
                        value={loading ? '—' : `$${(overview?.estimated_cost_usd ?? 0).toFixed(4)}`}
                        hint={`${(overview?.total_tokens ?? 0).toLocaleString()} tokens used`}
                    />
                </section>

                <div className="grid gap-4 lg:grid-cols-3">
                    <Panel className="min-w-0 lg:col-span-2">
                        <PanelHeader
                            title="Recent documents"
                            description="Latest additions and their index state"
                            action={
                                <Link to="/documents" className="btn-ghost btn-sm">
                                    All documents
                                    <ArrowUpRight className="h-3.5 w-3.5" strokeWidth={1.75} />
                                </Link>
                            }
                        />
                        {loading ? (
                            <div className="space-y-3 p-5 sm:p-6">
                                {[0, 1, 2].map((row) => (
                                    <div key={row} className="skeleton h-12 w-full" />
                                ))}
                            </div>
                        ) : recentDocuments.length === 0 ? (
                            <div className="p-5 sm:p-6">
                                <EmptyState
                                    icon={FileText}
                                    title="No documents yet"
                                    description="Upload a guideline, paper or protocol to start building your evidence base."
                                    action={
                                        <Link to="/documents" className="btn-primary btn-sm">
                                            <Plus className="h-4 w-4" strokeWidth={1.75} />
                                            Add a document
                                        </Link>
                                    }
                                />
                            </div>
                        ) : (
                            <ul className="divide-y divide-line">
                                {recentDocuments.map((doc) => {
                                    const meta = documentStatusMeta(doc.status);
                                    return (
                                        <li
                                            key={doc.id}
                                            className="flex items-center gap-3 px-5 py-3.5 transition-colors hover:bg-paper-wash sm:px-6"
                                        >
                                            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[9px] border border-line bg-paper-wash text-ink-muted">
                                                <FileText className="h-4 w-4" strokeWidth={1.7} />
                                            </span>
                                            <div className="min-w-0 flex-1">
                                                <p className="truncate text-[13px] font-medium text-ink">
                                                    {doc.filename}
                                                </p>
                                                <p className="meta mt-0.5 truncate">
                                                    {formatFileSize(doc.file_size)}
                                                    {doc.page_count > 0 ? ` · ${doc.page_count} pages` : ''}
                                                    {doc.chunk_count > 0
                                                        ? ` · ${doc.chunk_count} passages`
                                                        : ''}
                                                </p>
                                            </div>
                                            <Badge tone={meta.tone}>{meta.label}</Badge>
                                        </li>
                                    );
                                })}
                            </ul>
                        )}
                    </Panel>

                    <div className="grid min-w-0 gap-4">
                        <Panel>
                            <PanelHeader title="Index state" />
                            <dl className="px-5 py-4 text-[13px] sm:px-6">
                                {[
                                    { label: 'Indexed', value: indexState.indexed },
                                    { label: 'Processing', value: indexState.pending },
                                    { label: 'Needs attention', value: indexState.attention },
                                ].map((row) => (
                                    <div
                                        key={row.label}
                                        className="flex items-center justify-between border-b border-line py-2.5 last:border-0 last:pb-0"
                                    >
                                        <dt className="text-ink-soft">{row.label}</dt>
                                        <dd className="tabular font-medium text-ink">{row.value}</dd>
                                    </div>
                                ))}
                            </dl>
                        </Panel>

                        <Panel className="overflow-hidden">
                            <PanelHeader title="Go to" />
                            <nav className="divide-y divide-line">
                                {[
                                    {
                                        to: '/documents',
                                        label: 'Add documents',
                                        hint: 'PDF, Word, CSV, scans',
                                        icon: Upload,
                                    },
                                    {
                                        to: '/chat',
                                        label: 'Ask a question',
                                        hint: 'Page-level citations',
                                        icon: MessageSquare,
                                    },
                                ].map((action) => (
                                    <Link
                                        key={action.to}
                                        to={action.to}
                                        className="flex items-center gap-3 px-5 py-3 transition-colors hover:bg-paper-wash sm:px-6"
                                    >
                                        <action.icon
                                            className="h-4 w-4 shrink-0 text-ink-muted"
                                            strokeWidth={1.75}
                                        />
                                        <span className="min-w-0 flex-1">
                                            <span className="block text-[13px] font-medium text-ink">
                                                {action.label}
                                            </span>
                                            <span className="block text-[11.5px] text-ink-muted">
                                                {action.hint}
                                            </span>
                                        </span>
                                        <ArrowUpRight
                                            className="h-3.5 w-3.5 text-ink-muted"
                                            strokeWidth={1.75}
                                        />
                                    </Link>
                                ))}
                            </nav>
                        </Panel>
                    </div>
                </div>

                <Panel className="min-w-0">
                    <PanelHeader
                        title="Recent questions"
                        description="Your last questions and when they were asked"
                        action={
                            <Link to="/chat" className="btn-ghost btn-sm">
                                Open assistant
                                <ArrowUpRight className="h-3.5 w-3.5" strokeWidth={1.75} />
                            </Link>
                        }
                    />
                    {loading ? (
                        <div className="space-y-3 p-5 sm:p-6">
                            {[0, 1].map((row) => (
                                <div key={row} className="skeleton h-10 w-full" />
                            ))}
                        </div>
                    ) : history.length === 0 ? (
                        <div className="p-5 sm:p-6">
                            <EmptyState
                                icon={MessageSquare}
                                title="No questions yet"
                                description="Ask about a guideline value, dosage, table or finding in your documents."
                                action={
                                    <Link to="/chat" className="btn-secondary btn-sm">
                                        Ask the assistant
                                    </Link>
                                }
                            />
                        </div>
                    ) : (
                        <ul className="divide-y divide-line">
                            {history.map((item) => (
                                <li key={item.id}>
                                    <Link
                                        to="/chat"
                                        className="flex items-center gap-3 px-5 py-3.5 transition-colors hover:bg-paper-wash sm:px-6"
                                    >
                                        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-sky-400" />
                                        <p className="min-w-0 flex-1 truncate text-[13px] text-ink">
                                            {item.question}
                                        </p>
                                        <span className="meta shrink-0">
                                            {formatRelativeTime(item.timestamp)}
                                        </span>
                                    </Link>
                                </li>
                            ))}
                        </ul>
                    )}
                </Panel>
            </div>
        </Shell>
    );
};

export default DashboardPage;
