import api from './api';

export interface UsageOverview {
    total_documents: number;
    total_queries: number;
    total_tokens: number;
    avg_response_time: number;
    completed_documents: number;
    processing_documents: number;
    rejected_documents: number;
    failed_documents: number;
    insufficient_evidence_queries: number;
    web_fallback_queries: number;
    estimated_cost_usd: number;
}

export interface UsageDataPoint {
    date: string;
    queries: number;
    documents: number;
}

export interface UsageGraphData {
    data_points: UsageDataPoint[];
    period: string;
}

export interface TopicData {
    topic: string;
    count: number;
}

export interface TopTopics {
    topics: TopicData[];
}

export interface ObservabilityOverview {
    total_requests: number;
    avg_latency_ms: number;
    p95_latency_ms: number;
    avg_retrieval_attempts: number;
    prompt_tokens: number;
    completion_tokens: number;
    estimated_cost_usd: number;
    abstention_rate: number;
    web_fallback_rate: number;
    error_count: number;
    latency: Record<string, number>;
}

export interface ProcessingStatus {
    status_counts: Record<string, number>;
    active_jobs: number;
    failed_jobs: number;
    recent_errors: Array<{
        id: string;
        filename: string;
        status: string;
        message?: string | null;
    }>;
}

const analyticsService = {
    getOverview: async (): Promise<UsageOverview> => {
        const response = await api.get<UsageOverview>('/api/v1/analytics/overview');
        return response.data;
    },

    getUsageGraph: async (period: 'daily' | 'weekly' = 'daily'): Promise<UsageGraphData> => {
        const response = await api.get<UsageGraphData>('/api/v1/analytics/usage-graph', {
            params: { period },
        });
        return response.data;
    },

    getTopTopics: async (limit: number = 5): Promise<TopTopics> => {
        const response = await api.get<TopTopics>('/api/v1/analytics/top-topics', {
            params: { limit },
        });
        return response.data;
    },

    getObservability: async (): Promise<ObservabilityOverview> => {
        const response = await api.get<ObservabilityOverview>('/api/v1/analytics/observability');
        return response.data;
    },

    getProcessingStatus: async (): Promise<ProcessingStatus> => {
        const response = await api.get<ProcessingStatus>('/api/v1/analytics/processing-status');
        return response.data;
    },
};

export default analyticsService;
