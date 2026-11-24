import axios from 'axios';

export const AUTH_MESSAGES = {
    invalidCredentials: 'Invalid email or password',
    network: 'Unable to connect to the server',
    unavailable: 'Authentication service is temporarily unavailable',
    validation: 'Please check the entered information',
    accountDisabled: 'Account is unavailable; contact support',
    session: 'Unable to establish your session. Please try again',
    rateLimited: 'Too many attempts. Please wait a moment and try again.',
    generic: 'Something went wrong. Please try again',
} as const;

/** Thrown when credentials were accepted but the profile could not be loaded. */
export class SessionError extends Error {
    constructor() {
        super(AUTH_MESSAGES.session);
        this.name = 'SessionError';
    }
}

function detailMessage(data: unknown): string | null {
    if (!data || typeof data !== 'object') return null;
    const detail = (data as { detail?: unknown }).detail;
    return typeof detail === 'string' && detail.trim() ? detail.trim() : null;
}

/**
 * Turn any authentication failure into a message a person can act on.
 * Internal details (stack traces, provider responses, tokens) never surface.
 */
export function describeAuthError(error: unknown): string {
    if (error instanceof SessionError) return AUTH_MESSAGES.session;

    if (!axios.isAxiosError(error)) {
        if (error instanceof Error && error.name === 'SessionError') return AUTH_MESSAGES.session;
        return AUTH_MESSAGES.generic;
    }

    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
        return AUTH_MESSAGES.unavailable;
    }

    if (!error.response) {
        // No response at all: server down, wrong port, or the browser blocked
        // the request (e.g. an origin missing from the API's CORS allow-list).
        console.warn(
            `[auth] no response from ${error.config?.baseURL ?? ''}${error.config?.url ?? ''}` +
                ` — the API is unreachable or blocked the request (${error.message}).`
        );
        return AUTH_MESSAGES.network;
    }

    const { status } = error.response;

    if (status === 401) return AUTH_MESSAGES.invalidCredentials;
    if (status === 403) return detailMessage(error.response.data) ?? AUTH_MESSAGES.accountDisabled;
    if (status === 400 || status === 422) {
        return detailMessage(error.response.data) ?? AUTH_MESSAGES.validation;
    }
    if (status === 429) return AUTH_MESSAGES.rateLimited;
    if (status === 502 || status === 503 || status === 504) return AUTH_MESSAGES.unavailable;

    console.warn(`[auth] unexpected authentication response (${status})`, error.response.data);
    return AUTH_MESSAGES.generic;
}
