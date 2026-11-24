/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                ink: {
                    DEFAULT: '#101828',
                    soft: '#475467',
                    muted: '#667085',
                },
                line: '#E8EEF4',
                paper: {
                    DEFAULT: '#FFFFFF',
                    wash: '#F8FAFC',
                    mist: '#F5F8FB',
                },
                sky: {
                    50: '#F3F8FD',
                    100: '#EAF4FC',
                    200: '#D8EAF8',
                    300: '#C2DFF3',
                    400: '#91C3E8',
                },
                royal: {
                    DEFAULT: '#2457C5',
                    hover: '#1D469F',
                    active: '#173A83',
                    soft: '#E8F0FE',
                },
                success: {
                    DEFAULT: '#65C987',
                    soft: '#EAF8EF',
                    ink: '#2E7D4F',
                },
                danger: {
                    DEFAULT: '#E56B73',
                    soft: '#FDF0F1',
                    ink: '#B02A33',
                },
                warning: {
                    DEFAULT: '#E9A23B',
                    soft: '#FFF6E7',
                    ink: '#8A5A12',
                },
            },
            fontFamily: {
                sans: ['Inter', 'system-ui', 'sans-serif'],
                display: ['Inter', 'system-ui', 'sans-serif'],
            },
            borderRadius: {
                input: '10px',
                btn: '10px',
                card: '16px',
                panel: '20px',
            },
            boxShadow: {
                card: '0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.03)',
                lift: '0 12px 28px -16px rgba(16, 24, 40, 0.22), 0 2px 6px rgba(16, 24, 40, 0.04)',
                plate: '0 20px 48px -32px rgba(23, 58, 131, 0.34)',
            },
            maxWidth: {
                shell: '1440px',
            },
            transitionTimingFunction: {
                calm: 'cubic-bezier(0.2, 0.7, 0.3, 1)',
            },
            keyframes: {
                riseIn: {
                    '0%': { opacity: '0', transform: 'translateY(6px)' },
                    '100%': { opacity: '1', transform: 'translateY(0)' },
                },
                fadeIn: {
                    '0%': { opacity: '0' },
                    '100%': { opacity: '1' },
                },
            },
            animation: {
                'rise-in': 'riseIn 0.28s cubic-bezier(0.2, 0.7, 0.3, 1) both',
                'fade-in': 'fadeIn 0.2s ease-out both',
            },
        },
    },
    plugins: [],
}
