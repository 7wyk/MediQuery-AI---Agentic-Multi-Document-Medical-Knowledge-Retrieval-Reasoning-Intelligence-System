import React, { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
    BarChart3,
    ChevronDown,
    FileText,
    LayoutGrid,
    LogOut,
    Menu,
    MessageSquare,
    X,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { cn } from '../../lib/utils';

const NAV = [
    { to: '/dashboard', label: 'Overview', icon: LayoutGrid },
    { to: '/documents', label: 'Documents', icon: FileText },
    { to: '/chat', label: 'Assistant', icon: MessageSquare },
    { to: '/analytics', label: 'Analytics', icon: BarChart3 },
];

export const BrandMark: React.FC<{ className?: string }> = ({ className }) => (
    <span
        className={cn(
            'flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-royal text-white',
            className
        )}
        aria-hidden="true"
    >
        <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none">
            <path d="M12 5.5v7M8.5 9h7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            <path
                d="M6.5 16h11M6.5 19h6.5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                opacity="0.55"
            />
        </svg>
    </span>
);

const initials = (name?: string | null) => {
    if (!name) return 'MQ';
    return name
        .trim()
        .split(/\s+/)
        .slice(0, 2)
        .map((part) => part[0]?.toUpperCase() ?? '')
        .join('');
};

interface ShellProps {
    children: React.ReactNode;
    wide?: boolean;
    footer?: boolean;
}

const Shell: React.FC<ShellProps> = ({ children, wide = true, footer = true }) => {
    const { user, logout } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();
    const [menuOpen, setMenuOpen] = useState(false);
    const [userOpen, setUserOpen] = useState(false);
    const userMenuRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        setMenuOpen(false);
        setUserOpen(false);
    }, [location.pathname]);

    useEffect(() => {
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setUserOpen(false);
                setMenuOpen(false);
            }
        };
        const onClick = (event: MouseEvent) => {
            if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
                setUserOpen(false);
            }
        };
        document.addEventListener('keydown', onKey);
        document.addEventListener('mousedown', onClick);
        return () => {
            document.removeEventListener('keydown', onKey);
            document.removeEventListener('mousedown', onClick);
        };
    }, []);

    const handleLogout = () => {
        logout();
        navigate('/');
    };

    return (
        <div className="flex min-h-screen flex-col bg-paper-wash">
            <header className="sticky top-0 z-40 border-b border-line bg-white">
                <div
                    className={cn(
                        'mx-auto flex h-16 items-center gap-3 px-4 sm:px-6 lg:px-8',
                        wide ? 'max-w-shell' : 'max-w-[1180px]'
                    )}
                >
                    <Link to="/dashboard" className="flex items-center gap-2.5">
                        <BrandMark />
                        <span className="leading-tight">
                            <span className="block text-[15px] font-medium tracking-tight text-ink">
                                MediQuery AI
                            </span>
                            <span className="hidden text-[11px] text-ink-muted sm:block">
                                Medical document intelligence
                            </span>
                        </span>
                    </Link>

                    <nav className="ml-6 hidden items-center gap-1 md:flex" aria-label="Main">
                        {NAV.map((item) => (
                            <NavLink
                                key={item.to}
                                to={item.to}
                                className={({ isActive }) =>
                                    cn(
                                        'inline-flex h-9 items-center gap-2 rounded-[9px] px-3 text-[13.5px] font-medium transition-colors duration-150',
                                        isActive
                                            ? 'bg-royal-soft text-royal'
                                            : 'text-ink-soft hover:bg-paper-wash hover:text-ink'
                                    )
                                }
                            >
                                <item.icon className="h-4 w-4" strokeWidth={1.75} />
                                {item.label}
                            </NavLink>
                        ))}
                    </nav>

                    <div className="ml-auto flex items-center gap-1.5">
                        <Link to="/chat" className="btn-primary btn-sm hidden lg:inline-flex">
                            <MessageSquare className="h-4 w-4" strokeWidth={1.75} />
                            New question
                        </Link>

                        <div className="relative" ref={userMenuRef}>
                            <button
                                type="button"
                                onClick={() => setUserOpen((open) => !open)}
                                className="flex h-10 items-center gap-2 rounded-btn px-1.5 transition-colors hover:bg-paper-wash"
                                aria-haspopup="menu"
                                aria-expanded={userOpen}
                                aria-label="Account menu"
                            >
                                <span className="flex h-8 w-8 items-center justify-center rounded-full border border-sky-300 bg-sky-50 text-[11px] font-medium text-royal">
                                    {initials(user?.full_name)}
                                </span>
                                <span className="hidden max-w-[140px] truncate text-[13px] font-medium text-ink lg:block">
                                    {user?.full_name || 'Account'}
                                </span>
                                <ChevronDown
                                    className="hidden h-4 w-4 text-ink-muted lg:block"
                                    strokeWidth={1.75}
                                />
                            </button>

                            {userOpen && (
                                <div
                                    role="menu"
                                    className="absolute right-0 top-12 w-64 animate-fade-in rounded-card border border-line bg-white p-1.5 shadow-lift"
                                >
                                    <div className="border-b border-line px-3 py-2.5">
                                        <p className="truncate text-[13px] font-medium text-ink">
                                            {user?.full_name || 'Signed in'}
                                        </p>
                                        <p className="truncate text-[12px] text-ink-muted">{user?.email}</p>
                                    </div>
                                    <div className="pt-1.5">
                                        {NAV.map((item) => (
                                            <Link
                                                key={item.to}
                                                to={item.to}
                                                role="menuitem"
                                                className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] text-ink-soft transition-colors hover:bg-paper-wash hover:text-ink"
                                            >
                                                <item.icon className="h-4 w-4" strokeWidth={1.75} />
                                                {item.label}
                                            </Link>
                                        ))}
                                    </div>
                                    <div className="mt-1 border-t border-line pt-1">
                                        <button
                                            type="button"
                                            role="menuitem"
                                            onClick={handleLogout}
                                            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] text-danger-ink transition-colors hover:bg-danger-soft"
                                        >
                                            <LogOut className="h-4 w-4" strokeWidth={1.75} />
                                            Sign out
                                        </button>
                                    </div>
                                </div>
                            )}
                        </div>

                        <button
                            type="button"
                            onClick={() => setMenuOpen((open) => !open)}
                            className="btn-icon md:hidden"
                            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
                            aria-expanded={menuOpen}
                        >
                            {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
                        </button>
                    </div>
                </div>

                {menuOpen && (
                    <div className="animate-fade-in border-t border-line bg-white px-4 pb-4 pt-2 md:hidden">
                        <nav className="flex flex-col gap-1" aria-label="Mobile">
                            {NAV.map((item) => (
                                <NavLink
                                    key={item.to}
                                    to={item.to}
                                    className={({ isActive }) =>
                                        cn(
                                            'flex h-10 items-center gap-2.5 rounded-[9px] px-3 text-[13.5px] font-medium',
                                            isActive ? 'bg-royal-soft text-royal' : 'text-ink-soft'
                                        )
                                    }
                                >
                                    <item.icon className="h-4 w-4" strokeWidth={1.75} />
                                    {item.label}
                                </NavLink>
                            ))}
                            <button
                                type="button"
                                onClick={handleLogout}
                                className="mt-1 flex h-10 items-center gap-2.5 rounded-[9px] px-3 text-[13.5px] font-medium text-danger-ink"
                            >
                                <LogOut className="h-4 w-4" strokeWidth={1.75} />
                                Sign out
                            </button>
                        </nav>
                    </div>
                )}
            </header>

            <main className="flex-1">{children}</main>

            {footer && (
                <footer className="border-t border-line bg-white">
                    <div
                        className={cn(
                            'mx-auto flex flex-col gap-2 px-4 py-5 text-[12px] text-ink-muted sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8',
                            wide ? 'max-w-shell' : 'max-w-[1180px]'
                        )}
                    >
                        <p>MediQuery AI supports clinical reading. It does not replace professional judgement.</p>
                        <p className="tabular">Documents stay private to your account</p>
                    </div>
                </footer>
            )}
        </div>
    );
};

export default Shell;
