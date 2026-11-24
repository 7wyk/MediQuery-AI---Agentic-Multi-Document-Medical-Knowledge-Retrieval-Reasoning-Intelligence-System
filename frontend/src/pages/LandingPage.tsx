import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
    ArrowRight,
    BookOpen,
    Check,
    FileSearch,
    FileText,
    Files,
    Layers,
    Menu,
    MessageSquare,
    Quote,
    ShieldCheck,
    Upload,
    X,
} from 'lucide-react';
import { BrandMark } from '../components/layout/Shell';

const HERO_IMAGE = '/mediquery-hero-doctor.webp';

const TRUST = ['Document-grounded answers', 'Page-level citations', 'Evidence-aware responses'];

const STEPS = [
    {
        icon: Upload,
        title: 'Upload medical documents',
        body: 'Add the guidelines, papers and protocols you already trust. PDFs, Word and Excel files, CSVs, text and scans are screened for medical relevance before indexing.',
    },
    {
        icon: MessageSquare,
        title: 'Ask in natural language',
        body: 'Put the question the way you would ask a colleague. It is rewritten into retrieval queries, reranked against your own corpus and graded for evidence coverage.',
    },
    {
        icon: Quote,
        title: 'Read evidence-grounded answers',
        body: 'Answers come back with page-level citations you can open, and an honest abstention when your documents cannot support the claim.',
    },
];

const CAPABILITIES = [
    {
        icon: Files,
        title: 'Medical document ingestion',
        body: 'Documents are accepted per account and kept private to it, with each file screened for medical relevance before it joins the index.',
    },
    {
        icon: FileText,
        title: 'Document processing',
        body: 'Text, tables and figures are parsed and split into passages with their page and section intact, so structure survives into retrieval.',
    },
    {
        icon: FileSearch,
        title: 'Intelligent retrieval',
        body: 'Questions are rewritten into several retrieval queries, then reranked against your corpus instead of a generic web index.',
    },
    {
        icon: Layers,
        title: 'Standard RAG',
        body: 'A single retrieve-then-answer pass for direct questions, tuned to keep latency low while staying grounded in your documents.',
    },
    {
        icon: BookOpen,
        title: 'Agentic RAG',
        body: 'For questions that need several passes, retrieval is planned and repeated, with evidence re-checked between attempts before an answer is written.',
    },
    {
        icon: ShieldCheck,
        title: 'Evidence-grounded answers',
        body: 'Every sentence is checked against the retrieved passages. When the evidence is thin, the answer says so instead of guessing.',
    },
    {
        icon: Quote,
        title: 'Page-level citations',
        body: 'References point to the exact passage and the page it was read from, so a claim can be checked in seconds.',
    },
    {
        icon: ArrowRight,
        title: 'PDF source navigation',
        body: 'A citation opens the source document at the page the passage came from, not at the top of the file.',
    },
];

const LandingPage: React.FC = () => {
    const [menuOpen, setMenuOpen] = useState(false);

    useEffect(() => {
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') setMenuOpen(false);
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, []);

    return (
        <div className="min-h-screen bg-white">
            {/* ---------------- Navigation ---------------- */}
            <header className="sticky top-0 z-50 border-b border-white/10 bg-[#0B1119]/95 text-white backdrop-blur">
                <div className="mx-auto flex h-16 max-w-shell items-center gap-3 px-4 sm:px-6 lg:px-8">
                    <Link to="/" className="flex items-center gap-2.5">
                        <BrandMark />
                        <span className="leading-tight">
                            <span className="block text-[15px] font-medium tracking-tight text-white">
                                MediQuery AI
                            </span>
                            <span className="hidden text-[11px] text-white/50 sm:block">
                                Medical document intelligence
                            </span>
                        </span>
                    </Link>

                    <nav
                        className="mx-auto hidden items-center gap-7 md:flex"
                        aria-label="Sections"
                    >
                        <a
                            href="#how"
                            className="text-[13.5px] text-white/70 transition-colors hover:text-white"
                        >
                            How it works
                        </a>
                        <a
                            href="#capabilities"
                            className="text-[13.5px] text-white/70 transition-colors hover:text-white"
                        >
                            Capabilities
                        </a>
                        <a
                            href="#evidence"
                            className="text-[13.5px] text-white/70 transition-colors hover:text-white"
                        >
                            Evidence
                        </a>
                    </nav>

                    <div className="ml-auto flex items-center gap-2 md:ml-0">
                        <Link
                            to="/login"
                            className="hidden h-9 items-center rounded-btn px-3 text-[13.5px] font-medium text-white/80 transition-colors hover:bg-white/10 hover:text-white sm:inline-flex"
                        >
                            Sign in
                        </Link>
                        <Link
                            to="/register"
                            className="inline-flex h-9 items-center gap-2 rounded-btn bg-royal px-3.5 text-[13.5px] font-medium text-white transition-colors hover:bg-royal-hover"
                        >
                            Get started
                        </Link>
                        <button
                            type="button"
                            onClick={() => setMenuOpen((open) => !open)}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-btn text-white/80 transition-colors hover:bg-white/10 hover:text-white md:hidden"
                            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
                            aria-expanded={menuOpen}
                        >
                            {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
                        </button>
                    </div>
                </div>

                {menuOpen && (
                    <div className="animate-fade-in border-t border-white/10 bg-[#0B1119] px-4 pb-4 pt-2 md:hidden">
                        <nav className="flex flex-col" aria-label="Mobile">
                            {[
                                { href: '#how', label: 'How it works' },
                                { href: '#capabilities', label: 'Capabilities' },
                                { href: '#evidence', label: 'Evidence' },
                            ].map((item) => (
                                <a
                                    key={item.href}
                                    href={item.href}
                                    onClick={() => setMenuOpen(false)}
                                    className="flex h-11 items-center border-b border-white/5 text-[14px] text-white/75 transition-colors hover:text-white"
                                >
                                    {item.label}
                                </a>
                            ))}
                            <Link
                                to="/login"
                                className="flex h-11 items-center text-[14px] text-white/75 transition-colors hover:text-white"
                            >
                                Sign in
                            </Link>
                        </nav>
                    </div>
                )}
            </header>

            <main>
                {/* ---------------- Hero ---------------- */}
                <section className="relative isolate overflow-hidden bg-[#081020]">
                    <img
                        src={HERO_IMAGE}
                        alt="Physician in a white coat seated at a desk with a laptop in a modern medical office"
                        width={1600}
                        height={1067}
                        decoding="async"
                        className="absolute inset-0 h-full w-full object-cover object-[42%_22%] sm:object-[36%_20%] lg:object-[45%_35%]"
                    />

                    {/* Mobile / tablet: bottom-weighted darkening so the face stays visible */}
                    <div
                        aria-hidden="true"
                        className="absolute inset-0 bg-[linear-gradient(180deg,rgba(6,14,26,0.12)_0%,rgba(6,14,26,0.32)_34%,rgba(6,14,26,0.88)_72%,rgba(6,14,26,0.96)_100%)] lg:hidden"
                    />
                    {/* Desktop: cinematic left-to-right overlay */}
                    <div
                        aria-hidden="true"
                        className="absolute inset-0 hidden bg-[linear-gradient(90deg,rgba(6,14,26,0.16)_0%,rgba(6,14,26,0.42)_34%,rgba(6,14,26,0.82)_58%,rgba(6,14,26,0.93)_78%,rgba(6,14,26,0.95)_100%)] lg:block"
                    />
                    {/* Subtle base darkening to keep the photograph from fighting the type */}
                    <div aria-hidden="true" className="absolute inset-0 bg-[#060E1A]/15" />

                    <div className="relative mx-auto flex min-h-[720px] max-w-shell flex-col justify-end sm:min-h-[680px] px-4 pb-12 pt-14 sm:px-6 sm:pb-16 sm:pt-16 lg:h-[calc(100vh-4rem)] lg:max-h-[860px] lg:min-h-[640px] lg:justify-center lg:px-8 lg:pb-24 lg:pt-20">
                        <div className="w-full lg:ml-auto lg:max-w-[620px] xl:max-w-[740px]">
                            <p className="flex items-center gap-3 text-[10.5px] font-medium uppercase tracking-[0.18em] text-white/65 sm:text-[11px]">
                                <span
                                    className="h-[2px] w-6 rounded-full bg-royal"
                                    aria-hidden="true"
                                />
                                Medical document intelligence
                            </p>

                            <h1 className="mt-4 text-[30px] font-medium leading-[1.14] tracking-[-0.02em] text-white sm:mt-5 sm:text-[40px] sm:leading-[1.1] lg:text-[50px] xl:text-[58px]">
                                <span className="block">
                                    Medical answers
                                    <br className="hidden lg:block" /> you can trust.
                                </span>
                                <span className="mt-1 block text-white/80">
                                    Evidence you can verify.
                                </span>
                            </h1>

                            <p className="mt-3.5 max-w-[540px] text-[13.5px] leading-[1.65] text-white/70 sm:mt-5 sm:text-[15.5px] sm:leading-[1.7]">
                                MediQuery AI helps you explore medical guidelines, research papers and
                                clinical documents through intelligent, evidence-grounded answers with
                                page-level citations.
                            </p>

                            <div className="mt-6 flex items-center gap-2 sm:mt-8 sm:gap-2.5">
                                <Link
                                    to="/register"
                                    className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-btn bg-royal px-4 text-[13px] font-medium text-white transition-colors hover:bg-royal-hover sm:h-11 sm:flex-none sm:px-5 sm:text-[14px]"
                                >
                                    Get started
                                    <ArrowRight className="h-4 w-4" strokeWidth={1.9} />
                                </Link>
                                <a
                                    href="#capabilities"
                                    className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-btn border border-white/25 bg-white/5 px-4 text-[13px] font-medium text-white transition-colors hover:border-white/45 hover:bg-white/10 sm:h-11 sm:flex-none sm:px-5 sm:text-[14px]"
                                >
                                    Explore capabilities
                                </a>
                            </div>

                            <ul className="mt-6 flex flex-wrap gap-x-4 gap-y-1.5 text-[11.5px] text-white/60 sm:mt-9 sm:gap-x-5 sm:text-[12.5px]">
                                {TRUST.map((item) => (
                                    <li key={item} className="flex items-center gap-2">
                                        <Check
                                            className="h-3.5 w-3.5 text-royal/90"
                                            strokeWidth={2.2}
                                        />
                                        {item}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    </div>
                </section>

                {/* ---------------- How it works ---------------- */}
                <section id="how" className="scroll-mt-20 border-b border-line bg-white">
                    <div className="mx-auto max-w-shell px-4 py-16 sm:px-6 sm:py-20 lg:px-8">
                        <div className="max-w-2xl">
                            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-royal">
                                The workflow
                            </p>
                            <h2 className="mt-3 text-[26px] font-medium tracking-tight text-ink sm:text-[32px]">
                                How a question becomes a cited answer
                            </h2>
                            <p className="mt-3 text-[14px] leading-relaxed text-ink-soft">
                                Three steps, and every one of them leaves a record you can inspect.
                            </p>
                        </div>

                        <ol className="mt-12 grid gap-8 sm:grid-cols-3 sm:gap-6">
                            {STEPS.map((step, index) => (
                                <li key={step.title} className="border-t border-line pt-6">
                                    <div className="flex items-center gap-3">
                                        <span className="flex h-9 w-9 items-center justify-center rounded-[9px] border border-line bg-sky-50 text-royal">
                                            <step.icon className="h-4 w-4" strokeWidth={1.7} />
                                        </span>
                                        <span className="tabular text-[11.5px] font-medium text-ink-muted">
                                            {String(index + 1).padStart(2, '0')}
                                        </span>
                                    </div>
                                    <h3 className="mt-4 text-[16px] font-medium text-ink">
                                        {step.title}
                                    </h3>
                                    <p className="mt-2 text-[13.5px] leading-relaxed text-ink-soft">
                                        {step.body}
                                    </p>
                                </li>
                            ))}
                        </ol>
                    </div>
                </section>

                {/* ---------------- Capabilities ---------------- */}
                <section
                    id="capabilities"
                    className="scroll-mt-20 border-b border-line bg-paper-wash"
                >
                    <div className="mx-auto max-w-shell px-4 py-16 sm:px-6 sm:py-20 lg:px-8">
                        <div className="max-w-2xl">
                            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-royal">
                                Capabilities
                            </p>
                            <h2 className="mt-3 text-[26px] font-medium tracking-tight text-ink sm:text-[32px]">
                                What the platform does
                            </h2>
                            <p className="mt-3 text-[14px] leading-relaxed text-ink-soft">
                                The retrieval pipeline is the product. Everything else stays out of its
                                way.
                            </p>
                        </div>

                        <div className="mt-11 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                            {CAPABILITIES.map((item) => (
                                <article
                                    key={item.title}
                                    className="rounded-card border border-line bg-white p-5 transition-shadow duration-200 hover:shadow-lift"
                                >
                                    <span className="flex h-9 w-9 items-center justify-center rounded-[9px] border border-line bg-sky-50 text-royal">
                                        <item.icon className="h-4 w-4" strokeWidth={1.7} />
                                    </span>
                                    <h3 className="mt-4 text-[14px] font-medium text-ink">
                                        {item.title}
                                    </h3>
                                    <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-soft">
                                        {item.body}
                                    </p>
                                </article>
                            ))}
                        </div>
                    </div>
                </section>

                {/* ---------------- Evidence and citations ---------------- */}
                <section id="evidence" className="scroll-mt-20 border-b border-line bg-white">
                    <div className="mx-auto grid max-w-shell gap-12 px-4 py-16 sm:px-6 sm:py-20 lg:grid-cols-[minmax(0,1fr)_minmax(0,520px)] lg:items-center lg:gap-16 lg:px-8">
                        <div className="max-w-xl">
                            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-royal">
                                Evidence and citations
                            </p>
                            <h2 className="mt-3 text-[26px] font-medium tracking-tight text-ink sm:text-[32px]">
                                Read the answer, then check the page
                            </h2>
                            <p className="mt-3 text-[14px] leading-relaxed text-ink-soft">
                                An answer is only useful if you can trace it back. Every citation in
                                MediQuery AI carries the document, the section and the page the passage
                                was read from, so verification takes seconds rather than a search
                                through a PDF.
                            </p>

                            <ul className="mt-7 space-y-3">
                                {[
                                    'References open the source document at the cited page.',
                                    'Sentences are checked against the retrieved passages before they are shown.',
                                    'When the evidence is thin, the answer abstains and says what is missing.',
                                ].map((line) => (
                                    <li
                                        key={line}
                                        className="flex items-start gap-2.5 text-[13.5px] leading-relaxed text-ink-soft"
                                    >
                                        <Check
                                            className="mt-0.5 h-4 w-4 shrink-0 text-royal"
                                            strokeWidth={2}
                                        />
                                        {line}
                                    </li>
                                ))}
                            </ul>

                            <Link
                                to="/register"
                                className="mt-8 inline-flex h-10 items-center gap-2 rounded-btn bg-royal px-4 text-[13.5px] font-medium text-white transition-colors hover:bg-royal-hover"
                            >
                                Try it on your documents
                                <ArrowRight className="h-4 w-4" strokeWidth={1.9} />
                            </Link>
                        </div>

                        <div className="rounded-panel border border-line bg-paper-wash p-2 shadow-plate">
                            <div className="overflow-hidden rounded-[14px] border border-line bg-white">
                                <div className="flex items-center gap-2 border-b border-line bg-white px-4 py-2.5">
                                    <span className="flex h-6 w-6 items-center justify-center rounded-[7px] bg-royal text-white">
                                        <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none">
                                            <path
                                                d="M12 5.5v7M8.5 9h7"
                                                stroke="currentColor"
                                                strokeWidth="2.2"
                                                strokeLinecap="round"
                                            />
                                        </svg>
                                    </span>
                                    <span className="text-[12px] font-medium text-ink">
                                        Medical assistant
                                    </span>
                                    <span className="ml-auto rounded-full border border-line bg-paper-wash px-2 py-0.5 text-[10.5px] text-ink-muted">
                                        Agentic RAG
                                    </span>
                                </div>

                                <div className="space-y-3 p-3.5">
                                    <div className="flex justify-end">
                                        <p className="max-w-[85%] rounded-[12px] rounded-br-[4px] bg-royal px-3 py-2 text-[11.5px] leading-relaxed text-white">
                                            What is first-line treatment, and when is it escalated?
                                        </p>
                                    </div>

                                    <div className="rounded-[12px] border border-line bg-white p-3">
                                        <div className="mb-2 flex items-center gap-1.5">
                                            <span className="h-1.5 w-1.5 rounded-full bg-royal" />
                                            <span className="text-[10.5px] text-ink-muted">
                                                Evidence sufficient · 2 passages retained
                                            </span>
                                        </div>
                                        <p className="text-[11.5px] leading-[1.65] text-ink">
                                            Treatment starts with lifestyle measures for everyone.
                                            <span className="ref mx-1">1</span>
                                            Pharmacological therapy is added when cardiovascular risk is
                                            high or measures alone are insufficient.
                                            <span className="ref mx-1">2</span>
                                        </p>
                                        <div className="mt-2.5 space-y-1.5 border-t border-line pt-2">
                                            {[
                                                { n: 1, label: 'Clinical guideline · page 12' },
                                                { n: 2, label: 'Treatment protocol · page 4' },
                                            ].map((source) => (
                                                <div key={source.n} className="flex items-center gap-2">
                                                    <span className="ref">{source.n}</span>
                                                    <FileText
                                                        className="h-3 w-3 text-ink-muted"
                                                        strokeWidth={1.75}
                                                    />
                                                    <span className="text-[10.5px] text-ink-soft">
                                                        {source.label}
                                                    </span>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>

                                <div className="border-t border-line bg-white px-3 py-2">
                                    <div className="flex items-center gap-2 rounded-[9px] border border-line px-2.5 py-1.5">
                                        <span className="text-[11px] text-ink-muted">
                                            Ask about your documents
                                        </span>
                                        <span className="ml-auto flex h-6 w-6 items-center justify-center rounded-[7px] bg-royal text-white">
                                            <ArrowRight className="h-3 w-3" strokeWidth={2} />
                                        </span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </section>

                {/* ---------------- Call to action ---------------- */}
                <section className="bg-sky-100">
                    <div className="mx-auto max-w-shell px-4 py-16 sm:px-6 sm:py-20 lg:px-8">
                        <div className="mx-auto max-w-3xl text-center">
                            <h2 className="text-[26px] font-medium leading-tight tracking-tight text-ink sm:text-[34px]">
                                Make your medical documents easier to understand.
                            </h2>
                            <p className="mx-auto mt-3 max-w-xl text-[14px] leading-relaxed text-ink-soft">
                                Start with one guideline you already trust and ask it a question you know
                                the answer to. The citations are the proof.
                            </p>
                            <div className="mt-8 flex flex-col items-center justify-center gap-2.5 sm:flex-row">
                                <Link
                                    to="/register"
                                    className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-btn bg-royal px-5 text-[14px] font-medium text-white transition-colors hover:bg-royal-hover sm:w-auto"
                                >
                                    Get started with MediQuery AI
                                    <ArrowRight className="h-4 w-4" strokeWidth={1.9} />
                                </Link>
                                <Link
                                    to="/login"
                                    className="inline-flex h-11 w-full items-center justify-center rounded-btn border border-ink/15 bg-transparent px-5 text-[14px] font-medium text-ink transition-colors hover:border-ink/30 hover:bg-white/60 sm:w-auto"
                                >
                                    Sign in
                                </Link>
                            </div>
                        </div>
                    </div>
                </section>
            </main>

            {/* ---------------- Footer ---------------- */}
            <footer className="bg-[#0B1119] text-white">
                <div className="mx-auto max-w-shell px-4 py-12 sm:px-6 lg:px-8">
                    <div className="grid gap-9 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1.2fr)]">
                        <div>
                            <div className="flex items-center gap-2.5">
                                <BrandMark />
                                <span className="text-[14px] font-medium text-white">
                                    MediQuery AI
                                </span>
                            </div>
                            <p className="mt-3 max-w-xs text-[12.5px] leading-relaxed text-white/50">
                                Evidence-grounded document intelligence for medical reading, built on
                                retrieval augmented generation.
                            </p>
                        </div>

                        <div>
                            <p className="text-[12px] font-medium text-white/80">Product</p>
                            <ul className="mt-2.5 space-y-1.5 text-[12.5px] text-white/50">
                                <li>
                                    <Link to="/login" className="transition-colors hover:text-white">
                                        Sign in
                                    </Link>
                                </li>
                                <li>
                                    <Link
                                        to="/register"
                                        className="transition-colors hover:text-white"
                                    >
                                        Create an account
                                    </Link>
                                </li>
                                <li>
                                    <a href="#how" className="transition-colors hover:text-white">
                                        How it works
                                    </a>
                                </li>
                                <li>
                                    <a
                                        href="#capabilities"
                                        className="transition-colors hover:text-white"
                                    >
                                        Capabilities
                                    </a>
                                </li>
                            </ul>
                        </div>

                        <div className="rounded-input border border-white/10 bg-white/[0.04] px-4 py-3">
                            <p className="text-[11.5px] font-medium text-white/80">Clinical note</p>
                            <p className="mt-1 text-[11.5px] leading-relaxed text-white/45">
                                MediQuery AI is for informational use. It does not provide a diagnosis
                                and is not a substitute for qualified clinical judgement.
                            </p>
                        </div>
                    </div>

                    <p className="mt-9 border-t border-white/10 pt-5 text-[11.5px] text-white/40">
                        © 2026 MediQuery AI
                    </p>
                </div>
            </footer>
        </div>
    );
};

export default LandingPage;
