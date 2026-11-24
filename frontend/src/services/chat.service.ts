import api from './api';

export interface ChatQuery {
    question: string;
    language?: string;
    mode?: 'standard' | 'agentic';
    allow_web_search?: boolean;
    document_ids?: string[];
    conversation_id?: number;
}

export interface SourceCitation {
    index: number;
    kind: 'document' | 'web';
    document_id?: string | null;
    filename?: string | null;
    page?: number | null;
    content_type?: string | null;
    table_id?: string | null;
    section?: string | null;
    snippet: string;
    title?: string | null;
    url?: string | null;
    publisher?: string | null;
    score?: number | null;
}

export interface ClaimVerification {
    claim: string;
    evidence_indexes: number[];
    supported: boolean;
}

export interface AgentMetadata {
    request_id?: string | null;
    original_question?: string | null;
    transformed_query?: string | null;
    query_transform_status?: string | null;
    query_transform_error?: string | null;
    retrieval_attempts: number;
    retrieval_refined: boolean;
    retrieval_improved?: boolean | null;
    documents_retrieved: number;
    passages_retained?: number;
    relevance_score: number;
    evidence_coverage?: number;
    evidence_threshold?: number;
    evidence_outcome?: string | null;
    abstention_reason?: string | null;
    verification_status?: string | null;
    steps: string[];
    fallback_to_standard: boolean;
    subqueries: string[];
    evidence_status: string;
    web_search_used: boolean;
    web_search_enabled: boolean;
    graph_rag_used: boolean;
    claims: ClaimVerification[];
    latency_ms: Record<string, number>;
    token_usage: Record<string, number>;
    estimated_cost_usd: number;
    reranker?: string | null;
    errors: string[];
}

export interface ChatResponse {
    answer: string;
    sources: SourceCitation[];
    response_time: number;
    language: string;
    mode?: string;
    evidence_status: string;
    insufficient_evidence: boolean;
    agent_metadata?: AgentMetadata | null;
    conversation_id?: number | null;
    conversation_title?: string | null;
}

export interface ChatHistoryItem {
    id: number;
    question: string;
    answer?: string | null;
    timestamp: string;
    language: string;
    sources?: SourceCitation[] | null;
}

export interface ChatHistoryResponse {
    history: ChatHistoryItem[];
    total: number;
}

export interface Conversation {
    id: number;
    title: string;
    is_pinned: boolean;
    created_at: string;
    updated_at: string;
    message_count: number;
}

export interface ConversationMessage {
    id: number;
    question: string;
    answer?: string | null;
    timestamp: string;
    language: string;
    mode?: string | null;
    sources?: SourceCitation[] | null;
    evidence_status?: string | null;
    insufficient_evidence: boolean;
}

export interface ConversationDetail extends Conversation {
    messages: ConversationMessage[];
}

export interface ConversationListResponse {
    conversations: Conversation[];
    total: number;
}

const chatService = {
    query: async (data: ChatQuery): Promise<ChatResponse> => {
        const response = await api.post<ChatResponse>('/api/v1/chat/query', data);
        return response.data;
    },

    queryMultilang: async (data: ChatQuery): Promise<ChatResponse> => {
        const response = await api.post<ChatResponse>('/api/v1/chat/query-multilang', data);
        return response.data;
    },

    getHistory: async (limit: number = 50): Promise<ChatHistoryResponse> => {
        const response = await api.get<ChatHistoryResponse>('/api/v1/chat/history', {
            params: { limit },
        });
        return response.data;
    },

    clearHistory: async (): Promise<void> => {
        await api.delete('/api/v1/chat/history');
    },

    listConversations: async (search?: string): Promise<ConversationListResponse> => {
        const response = await api.get<ConversationListResponse>('/api/v1/chat/conversations', {
            params: search && search.trim() ? { q: search.trim() } : undefined,
        });
        return response.data;
    },

    getConversation: async (conversationId: number): Promise<ConversationDetail> => {
        const response = await api.get<ConversationDetail>(
            `/api/v1/chat/conversations/${conversationId}`
        );
        return response.data;
    },

    renameConversation: async (conversationId: number, title: string): Promise<Conversation> => {
        const response = await api.patch<Conversation>(
            `/api/v1/chat/conversations/${conversationId}`,
            { title }
        );
        return response.data;
    },

    setPinned: async (conversationId: number, isPinned: boolean): Promise<Conversation> => {
        const response = await api.patch<Conversation>(
            `/api/v1/chat/conversations/${conversationId}`,
            { is_pinned: isPinned }
        );
        return response.data;
    },

    deleteConversation: async (conversationId: number): Promise<void> => {
        await api.delete(`/api/v1/chat/conversations/${conversationId}`);
    },
};

export default chatService;
