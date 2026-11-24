import axios from 'axios';

const configuredBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').trim();
const API_BASE_URL = (configuredBaseUrl || 'http://localhost:8000').replace(/\/+$/, '');

if (!configuredBaseUrl && import.meta.env.DEV) {
    console.warn('[api] VITE_API_BASE_URL is not set; falling back to', API_BASE_URL);
}

// Endpoints that must never trigger the refresh-and-retry flow: a 401 from any
// of them is the answer itself, not an expired session.
const AUTH_ENDPOINTS = ['/api/v1/auth/login', '/api/v1/auth/register', '/api/v1/auth/refresh'];

const api = axios.create({
    baseURL: API_BASE_URL,
    headers: {
        'Content-Type': 'application/json',
    },
    timeout: 120000,
});

// Request interceptor to add auth token
api.interceptors.request.use(
    (config) => {
        const token = localStorage.getItem('access_token');
        if (token) {
            config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
    },
    (error) => {
        return Promise.reject(error);
    }
);

let refreshInFlight: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
    if (!refreshInFlight) {
        refreshInFlight = (async () => {
            const refreshToken = localStorage.getItem('refresh_token');
            if (!refreshToken) {
                throw new Error('No refresh token stored');
            }
            const response = await axios.post(
                `${API_BASE_URL}/api/v1/auth/refresh`,
                { refresh_token: refreshToken },
                { headers: { 'Content-Type': 'application/json' } }
            );
            const { access_token, refresh_token } = response.data;
            localStorage.setItem('access_token', access_token);
            localStorage.setItem('refresh_token', refresh_token);
            return access_token as string;
        })().finally(() => {
            refreshInFlight = null;
        });
    }
    return refreshInFlight;
}

// Response interceptor: refresh an expired access token once, and never for an
// authentication call (that would turn a wrong password into a redirect).
api.interceptors.response.use(
    (response) => response,
    async (error) => {
        const originalRequest = error.config;
        const url: string = originalRequest?.url ?? '';
        const isAuthCall = AUTH_ENDPOINTS.some((path) => url.includes(path));

        if (
            !originalRequest ||
            isAuthCall ||
            error.response?.status !== 401 ||
            originalRequest._retry
        ) {
            return Promise.reject(error);
        }

        originalRequest._retry = true;

        try {
            const accessToken = await refreshAccessToken();
            originalRequest.headers = originalRequest.headers ?? {};
            originalRequest.headers.Authorization = `Bearer ${accessToken}`;
            return api(originalRequest);
        } catch (refreshError) {
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            // Only leave the page when the user is somewhere a session is needed.
            if (window.location.pathname !== '/login') {
                window.location.assign('/login');
            }
            return Promise.reject(refreshError);
        }
    }
);

export default api;
