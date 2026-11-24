import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { AlertCircle, ArrowLeft, FileText } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import authService from '../services/auth.service';
import { describeAuthError } from '../lib/authErrors';
import { BrandMark } from '../components/layout/Shell';

const AuthPage: React.FC = () => {
    const navigate = useNavigate();
    const location = useLocation();
    const { login } = useAuth();

    const isLogin = location.pathname === '/login';
    const [formData, setFormData] = useState({ email: '', password: '', full_name: '' });
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const updateField = (field: keyof typeof formData, value: string) => {
        setFormData((current) => ({ ...current, [field]: value }));
        // A message about the previous attempt should not survive an edit.
        if (error) setError('');
    };

    const handleSubmit = async (event: React.FormEvent) => {
        event.preventDefault();
        if (loading) return;

        setError('');
        setLoading(true);

        try {
            if (isLogin) {
                await login(formData.email, formData.password);
                navigate('/dashboard');
                return;
            }

            await authService.register({
                email: formData.email,
                password: formData.password,
                full_name: formData.full_name,
            });
            await login(formData.email, formData.password);
            navigate('/dashboard');
        } catch (err) {
            setError(describeAuthError(err));
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex min-h-screen bg-white">
            <aside className="relative hidden w-[46%] flex-col justify-between bg-sky-100 p-10 lg:flex">
                <Link to="/" className="flex items-center gap-2.5">
                    <BrandMark />
                    <span className="text-[15px] font-medium tracking-tight text-ink">MediQuery AI</span>
                </Link>

                <div className="max-w-md">
                    <span className="evidence-rule" aria-hidden="true" />
                    <h1 className="mt-4 text-[30px] font-medium leading-[1.2] tracking-tight text-ink">
                        Every answer opens to the page it came from
                    </h1>
                    <p className="mt-3 text-[13.5px] leading-relaxed text-ink-soft">
                        Upload your own guidelines, papers and protocols. Ask in plain language. Read the
                        passage behind each claim before you use it.
                    </p>

                    <div className="mt-8 rounded-card border border-white/70 bg-white/85 p-4 shadow-card backdrop-blur-sm">
                        <div className="flex items-center gap-2">
                            <span className="ref">1</span>
                            <span className="flex items-center gap-1.5 text-[12px] font-medium text-ink">
                                <FileText className="h-3.5 w-3.5 text-ink-muted" strokeWidth={1.75} />
                                Guideline · page 12
                            </span>
                            <span className="ml-auto rounded-full border border-success/30 bg-success-soft px-2 py-0.5 text-[10.5px] font-medium text-success-ink">
                                Verified
                            </span>
                        </div>
                        <p className="mt-2.5 text-[12.5px] leading-relaxed text-ink-soft">
                            First-line management begins with lifestyle measures, with treatment added
                            according to cardiovascular risk.
                        </p>
                        <div className="mt-3 flex items-center gap-3 border-t border-line pt-2.5 text-[11px] text-ink-muted">
                            <span>4 of 4 claims supported</span>
                            <span className="h-1 w-16 overflow-hidden rounded-full bg-sky-100">
                                <span className="block h-full w-full rounded-full bg-royal/70" />
                            </span>
                        </div>
                    </div>
                </div>

                <p className="max-w-sm text-[11.5px] leading-relaxed text-ink-muted">
                    MediQuery AI supports clinical reading. It does not replace professional judgement.
                </p>
            </aside>

            <main className="flex flex-1 flex-col">
                <div className="flex items-center justify-between px-5 py-5 sm:px-8">
                    <Link
                        to="/"
                        className="btn-ghost -ml-2 text-[12.5px]"
                    >
                        <ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.75} />
                        Back to home
                    </Link>
                    <div className="flex items-center gap-2 lg:hidden">
                        <BrandMark className="h-8 w-8" />
                        <span className="text-[14px] font-medium text-ink">MediQuery AI</span>
                    </div>
                </div>

                <div className="flex flex-1 items-center justify-center px-5 pb-12 sm:px-8">
                    <div className="w-full max-w-[380px]">
                        <h2 className="text-[24px] font-medium tracking-tight text-ink">
                            {isLogin ? 'Sign in' : 'Create your account'}
                        </h2>
                        <p className="mt-1.5 text-[13px] text-ink-muted">
                            {isLogin
                                ? 'Continue to your evidence workspace'
                                : 'One private workspace for your medical documents'}
                        </p>

                        {error && (
                            <div className="alert-danger mt-5 flex items-start gap-2">
                                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.75} />
                                <p role="alert">{error}</p>
                            </div>
                        )}

                        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
                            {!isLogin && (
                                <div>
                                    <label htmlFor="full_name" className="field-label">
                                        Full name
                                    </label>
                                    <input
                                        id="full_name"
                                        type="text"
                                        required
                                        autoComplete="name"
                                        className="input"
                                        value={formData.full_name}
                                        onChange={(event) =>
                                            updateField('full_name', event.target.value)
                                        }
                                        placeholder="Dr. Amara Okafor"
                                    />
                                </div>
                            )}

                            <div>
                                <label htmlFor="email" className="field-label">
                                    Email
                                </label>
                                <input
                                    id="email"
                                    type="email"
                                    required
                                    autoComplete="email"
                                    className="input"
                                    value={formData.email}
                                    onChange={(event) => updateField('email', event.target.value)}
                                    placeholder="you@clinic.org"
                                />
                            </div>

                            <div>
                                <label htmlFor="password" className="field-label">
                                    Password
                                </label>
                                <input
                                    id="password"
                                    type="password"
                                    required
                                    minLength={isLogin ? undefined : 8}
                                    maxLength={isLogin ? undefined : 72}
                                    autoComplete={isLogin ? 'current-password' : 'new-password'}
                                    className="input"
                                    value={formData.password}
                                    onChange={(event) => updateField('password', event.target.value)}
                                    placeholder="At least 8 characters"
                                />
                            </div>

                            <button
                                type="submit"
                                disabled={loading}
                                className="btn-primary w-full"
                                aria-busy={loading}
                            >
                                {loading ? (isLogin ? 'Signing in…' : 'Creating account…') : isLogin ? 'Sign in' : 'Create account'}
                            </button>
                        </form>

                        <p className="mt-5 text-center text-[12.5px] text-ink-muted">
                            {isLogin ? 'No account yet? ' : 'Already have an account? '}
                            <Link
                                to={isLogin ? '/register' : '/login'}
                                className="font-medium text-royal hover:underline"
                            >
                                {isLogin ? 'Create one' : 'Sign in'}
                            </Link>
                        </p>

                        <p className="mt-8 border-t border-line pt-4 text-[11px] leading-relaxed text-ink-muted">
                            Your documents and questions stay private to your account. Nothing is shared
                            between workspaces.
                        </p>
                    </div>
                </div>
            </main>
        </div>
    );
};

export default AuthPage;
