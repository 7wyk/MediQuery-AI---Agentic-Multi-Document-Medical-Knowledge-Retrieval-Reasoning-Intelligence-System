import React, { useEffect, useMemo, useState } from 'react';
import {
    Area,
    CartesianGrid,
    ComposedChart,
    Line,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts';
import { Activity, BarChart3 } from 'lucide-react';
import Shell from '../components/layout/Shell';
import PageHeader from '../components/layout/PageHeader';
import { EmptyState, Panel, PanelHeader, StatCard } from '../components/ui/Primitives';
import LoadingSpinner from '../components/common/LoadingSpinner';
import analyticsService, {
    ObservabilityOverview,
    ProcessingStatus,
    TopTopics,
    UsageGraphData,
    UsageOverview,
} from '../services/analytics.service';
import { cn } from '../lib/utils';

const AXIS = { fontSize: 11, fill: '#667085' };

const STAGE_LABELS: Record<string, string> = {
    retrieval_ms: 'Retrieval',
    rerank_ms: 'Rerank',
    embedding_ms: 'Embedding',
    generation_ms: 'Generation',
    llm_ms: 'LLM',
    verification_ms: 'Verification',
    web_search_ms: 'Web search',
    transform_ms: 'Query rewrite',
    grading_ms: 'Evidence grading',
    total_ms: 'Total',
};

const stageLabel = (stage: string) =>
    STAGE_LABELS[stage] ?? stage.replace(/_ms$/, '').replace(/_/g, ' ');

const ChartTooltip: React.FC<any> = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null;
    return (
        <div className="rounded-lg border border-line bg-white px-3 py-2 shadow-card">
            <p className="text-[11px] text-ink-muted">{label}</p>
            {payload.map((entry: any) => (
                <p key={entry.dataKey} className="tabular mt-0.5 text-[12px] text-ink">
                    <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle" style={{ background: entry.color }} />
                    {entry.dataKey === 'queries' ? 'Questions' : 'Documents'}: {entry.value}
                </p>
            ))}
        </div>
    );
};

const AnalyticsPage: React.FC = () => {
    const [overview, setOverview] = useState<UsageOverview | null>(null);
    const [graphData, setGraphData] = useState<UsageGraphData | null>(null);
    const [topics, setTopics] = useState<TopTopics | null>(null);
    const [observability, setObservability] = useState<ObservabilityOverview | null>(null);
    const [processing, setProcessing] = useState<ProcessingStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [period, setPeriod] = useState<'daily' | 'weekly'>('daily');

    useEffect(() => {
        let cancelled = false;

        const fetchAnalytics = async () => {
            const results = await Promise.allSettled([
                analyticsService.getOverview(),
                analyticsService.getUsageGraph(period),
                analyticsService.getTopTopics(5),
                analyticsService.getObservability(),
                analyticsService.getProcessingStatus(),
            ]);
            if (cancelled) return;

            const [overviewRes, graphRes, topicsRes, observabilityRes, processingRes] = results;
            if (overviewRes.status === 'fulfilled') setOverview(overviewRes.value);
            if (graphRes.status === 'fulfilled') setGraphData(graphRes.value);
            if (topicsRes.status === 'fulfilled') setTopics(topicsRes.value);
            if (observabilityRes.status === 'fulfilled') setObservability(observabilityRes.value);
            if (processingRes.status === 'fulfilled') setProcessing(processingRes.value);
            setLoading(false);
        };

        fetchAnalytics();
        return () => {
            cancelled = true;
        };
    }, [period]);

    const latencyRows = useMemo(() => {
        const entries = Object.entries(observability?.latency || {}).map(([stage, value]) => ({
            stage,
            value: Number(value) || 0,
        }));
        const max = Math.max(1, ...entries.map((entry) => entry.value));
        return entries.map((entry) => ({ ...entry, share: (entry.value / max) * 100 }));
    }, [observability]);

    const topicRows = useMemo(() => {
        const list = topics?.topics ?? [];
        const max = Math.max(1, ...list.map((topic) => topic.count));
        return list.map((topic) => ({ ...topic, share: (topic.count / max) * 100 }));
    }, [topics]);

    const statusRows = Object.entries(processing?.status_counts || {});

    if (loading) {
        return (
            <Shell>
                <PageHeader meta="Workspace telemetry" title="Usage and retrieval quality" />
                <LoadingSpinner className="py-24" size="lg" />
            </Shell>
        );
    }

    return (
        <Shell>
            <PageHeader
                meta="Workspace telemetry"
                title="Usage and retrieval quality"
                description="Production telemetry for your workspace, from document intake through evidence grading. This is not an evaluation benchmark."
                actions={
                    <div className="inline-flex rounded-btn border border-line bg-white p-0.5">
                        {(['daily', 'weekly'] as const).map((option) => (
                            <button
                                key={option}
                                type="button"
                                onClick={() => setPeriod(option)}
                                className={cn(
                                    'h-8 rounded-[7px] px-3 text-[12.5px] font-medium capitalize transition-colors duration-150',
                                    period === option
                                        ? 'bg-royal-soft text-royal'
                                        : 'text-ink-muted hover:text-ink'
                                )}
                                aria-pressed={period === option}
                            >
                                {option}
                            </button>
                        ))}
                    </div>
                }
            />

            <div className="mx-auto max-w-shell space-y-4 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
                <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <StatCard
                        label="Documents"
                        value={overview?.total_documents ?? 0}
                        hint={`${overview?.completed_documents ?? 0} indexed · ${overview?.rejected_documents ?? 0} rejected`}
                    />
                    <StatCard
                        label="Questions"
                        value={overview?.total_queries ?? 0}
                        hint={`${overview?.insufficient_evidence_queries ?? 0} abstained or rejected`}
                    />
                    <StatCard
                        label="Average response"
                        value={`${(overview?.avg_response_time ?? 0).toFixed(2)} s`}
                        hint={`p95 ${(observability?.p95_latency_ms ?? 0).toFixed(0)} ms`}
                    />
                    <StatCard
                        label="Estimated AI cost"
                        value={`$${(observability?.estimated_cost_usd ?? 0).toFixed(4)}`}
                        hint={`${((observability?.prompt_tokens ?? 0) + (observability?.completion_tokens ?? 0)).toLocaleString()} tokens`}
                    />
                </section>

                <div className="grid gap-4 lg:grid-cols-3">
                    <Panel className="min-w-0 lg:col-span-2">
                        <PanelHeader
                            title="Query activity"
                            description={`Questions and documents by ${period === 'daily' ? 'day' : 'week'}`}
                        />
                        <div className="px-2 py-4 sm:px-4">
                            {(graphData?.data_points?.length ?? 0) === 0 ? (
                                <EmptyState
                                    className="mx-4 my-4 border-0 bg-transparent"
                                    icon={BarChart3}
                                    title="No activity recorded"
                                    description="Questions and uploads appear here once you start using the workspace."
                                />
                            ) : (
                                <ResponsiveContainer width="100%" height={286}>
                                    <ComposedChart data={graphData?.data_points || []} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
                                        <CartesianGrid stroke="#EEF3F8" vertical={false} />
                                        <XAxis dataKey="date" tick={AXIS} axisLine={false} tickLine={false} dy={6} />
                                        <YAxis tick={AXIS} axisLine={false} tickLine={false} allowDecimals={false} />
                                        <Tooltip content={<ChartTooltip />} cursor={{ stroke: '#C2DFF3' }} />
                                        <Area
                                            type="monotone"
                                            dataKey="queries"
                                            stroke="#2457C5"
                                            strokeWidth={2}
                                            fill="#2457C5"
                                            fillOpacity={0.07}
                                            activeDot={{ r: 3, strokeWidth: 0 }}
                                        />
                                        <Line
                                            type="monotone"
                                            dataKey="documents"
                                            stroke="#91C3E8"
                                            strokeWidth={2}
                                            dot={false}
                                        />
                                    </ComposedChart>
                                </ResponsiveContainer>
                            )}
                        </div>
                        <div className="flex items-center gap-5 border-t border-line px-5 py-3 text-[11.5px] text-ink-muted sm:px-6">
                            <span className="flex items-center gap-1.5">
                                <span className="h-1.5 w-1.5 rounded-full bg-royal" />
                                Questions
                            </span>
                            <span className="flex items-center gap-1.5">
                                <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
                                Documents
                            </span>
                        </div>
                    </Panel>

                    <div className="grid min-w-0 gap-4">
                        <Panel>
                            <PanelHeader title="Retrieval quality" />
                            <div className="space-y-4 px-5 py-4 sm:px-6">
                                {[
                                    {
                                        label: 'Abstention rate',
                                        value: `${((observability?.abstention_rate ?? 0) * 100).toFixed(1)}%`,
                                        share: (observability?.abstention_rate ?? 0) * 100,
                                        hint: 'Answers stopped for weak evidence',
                                    },
                                    {
                                        label: 'External source rate',
                                        value: `${((observability?.web_fallback_rate ?? 0) * 100).toFixed(1)}%`,
                                        share: (observability?.web_fallback_rate ?? 0) * 100,
                                        hint: `${overview?.web_fallback_queries ?? 0} answers used web sources`,
                                    },
                                ].map((metric) => (
                                    <div key={metric.label}>
                                        <div className="flex items-baseline justify-between gap-2">
                                            <p className="text-[12.5px] text-ink-soft">{metric.label}</p>
                                            <p className="tabular text-[13px] font-medium text-ink">
                                                {metric.value}
                                            </p>
                                        </div>
                                        <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-sky-100">
                                            <div
                                                className="h-full rounded-full bg-royal/70"
                                                style={{ width: `${Math.min(100, metric.share)}%` }}
                                            />
                                        </div>
                                        <p className="mt-1 text-[11px] text-ink-muted">{metric.hint}</p>
                                    </div>
                                ))}
                                <div className="flex items-center justify-between border-t border-line pt-3">
                                    <p className="text-[12.5px] text-ink-soft">Avg retrieval attempts</p>
                                    <p className="tabular text-[13px] font-medium text-ink">
                                        {(observability?.avg_retrieval_attempts ?? 0).toFixed(1)}
                                    </p>
                                </div>
                                <div className="flex items-center justify-between">
                                    <p className="text-[12.5px] text-ink-soft">Requests recorded</p>
                                    <p className="tabular text-[13px] font-medium text-ink">
                                        {observability?.total_requests ?? 0}
                                    </p>
                                </div>
                            </div>
                        </Panel>

                        <Panel>
                            <PanelHeader title="Document processing" />
                            <div className="px-5 py-4 sm:px-6">
                                <div className="flex items-end justify-between">
                                    <div>
                                        <p className="label">Active jobs</p>
                                        <p className="tabular mt-1 text-[20px] font-medium text-ink">
                                            {processing?.active_jobs ?? 0}
                                        </p>
                                    </div>
                                    <p className="text-[12px] text-ink-muted">
                                        {processing?.failed_jobs ?? 0} failed
                                    </p>
                                </div>
                                {statusRows.length > 0 && (
                                    <dl className="mt-3 border-t border-line pt-3">
                                        {statusRows.map(([status, count]) => (
                                            <div
                                                key={status}
                                                className="flex items-center justify-between py-1 text-[12.5px]"
                                            >
                                                <dt className="capitalize text-ink-soft">{status}</dt>
                                                <dd className="tabular font-medium text-ink">{count}</dd>
                                            </div>
                                        ))}
                                    </dl>
                                )}
                                {processing && processing.recent_errors.length > 0 && (
                                    <div className="mt-3 border-t border-line pt-3">
                                        <p className="text-[11.5px] font-medium text-ink-muted">
                                            Recent issues
                                        </p>
                                        <ul className="mt-1.5 space-y-1.5">
                                            {processing.recent_errors.slice(0, 3).map((item) => (
                                                <li key={item.id} className="text-[11.5px] leading-snug text-ink-soft">
                                                    <span className="font-medium text-ink">{item.filename}</span>
                                                    {item.message ? ` — ${item.message}` : ''}
                                                </li>
                                            ))}
                                        </ul>
                                    </div>
                                )}
                            </div>
                        </Panel>
                    </div>
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                    <Panel className="min-w-0">
                        <PanelHeader
                            title="Top topics"
                            description="Most frequent subjects in your questions"
                        />
                        <div className="px-5 py-4 sm:px-6">
                            {topicRows.length === 0 ? (
                                <EmptyState
                                    className="border-0 bg-transparent py-6"
                                    icon={Activity}
                                    title="No topics yet"
                                    description="Topic shares appear after a few questions have been asked."
                                />
                            ) : (
                                <ol className="space-y-3">
                                    {topicRows.map((topic, index) => (
                                        <li key={topic.topic} className="flex items-center gap-3">
                                            <span className="tabular w-4 text-[11px] text-ink-muted">
                                                {index + 1}
                                            </span>
                                            <span className="min-w-0 flex-1">
                                                <span className="flex items-baseline justify-between gap-2">
                                                    <span className="truncate text-[12.5px] text-ink-soft">
                                                        {topic.topic}
                                                    </span>
                                                    <span className="tabular text-[12px] text-ink">
                                                        {topic.count}
                                                    </span>
                                                </span>
                                                <span className="mt-1 block h-1 overflow-hidden rounded-full bg-sky-100">
                                                    <span
                                                        className="block h-full rounded-full bg-royal/80"
                                                        style={{ width: `${topic.share}%` }}
                                                    />
                                                </span>
                                            </span>
                                        </li>
                                    ))}
                                </ol>
                            )}
                        </div>
                    </Panel>

                    <Panel className="min-w-0">
                        <PanelHeader
                            title="Latency breakdown"
                            description="Average milliseconds per pipeline stage"
                        />
                        <div className="px-5 py-4 sm:px-6">
                            {latencyRows.length === 0 ? (
                                <EmptyState
                                    className="border-0 bg-transparent py-6"
                                    icon={Activity}
                                    title="No requests recorded"
                                    description="Stage timings appear after the first answered question."
                                />
                            ) : (
                                <ul className="space-y-3">
                                    {latencyRows.map((row) => (
                                        <li key={row.stage}>
                                            <div className="flex items-baseline justify-between gap-2">
                                                <span className="text-[12.5px] text-ink-soft">
                                                    {stageLabel(row.stage)}
                                                </span>
                                                <span className="tabular text-[12px] text-ink">
                                                    {row.value.toFixed(0)} ms
                                                </span>
                                            </div>
                                            <div className="mt-1 h-1 overflow-hidden rounded-full bg-sky-100">
                                                <div
                                                    className="h-full rounded-full bg-royal/80"
                                                    style={{
                                                        width: row.share > 0 ? `${Math.max(2, row.share)}%` : '0%',
                                                    }}
                                                />
                                            </div>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    </Panel>
                </div>
            </div>
        </Shell>
    );
};

export default AnalyticsPage;
