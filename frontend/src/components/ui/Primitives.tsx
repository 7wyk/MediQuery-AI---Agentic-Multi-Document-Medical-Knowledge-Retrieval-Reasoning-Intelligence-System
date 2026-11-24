import React from 'react';
import { cn } from '../../lib/utils';

export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

const TONES: Record<Tone, { wrap: string; dot: string }> = {
    neutral: { wrap: 'border-line bg-paper-wash text-ink-soft', dot: 'bg-ink-muted' },
    info: { wrap: 'border-sky-300 bg-royal-soft text-royal', dot: 'bg-royal' },
    success: { wrap: 'border-success/30 bg-success-soft text-success-ink', dot: 'bg-success' },
    warning: { wrap: 'border-warning/30 bg-warning-soft text-warning-ink', dot: 'bg-warning' },
    danger: { wrap: 'border-danger/30 bg-danger-soft text-danger-ink', dot: 'bg-danger' },
};

interface BadgeProps {
    tone?: Tone;
    children: React.ReactNode;
    dot?: boolean;
    className?: string;
}

/** Quiet status label: hairline border, tinted surface, semantic dot. */
export const Badge: React.FC<BadgeProps> = ({ tone = 'neutral', children, dot = true, className }) => {
    const style = TONES[tone];
    return (
        <span
            className={cn(
                'inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-full border px-2 text-[11.5px] font-medium',
                style.wrap,
                className
            )}
        >
            {dot && <span className={cn('status-dot', style.dot)} aria-hidden="true" />}
            {children}
        </span>
    );
};

interface MetricProps {
    label: string;
    value: React.ReactNode;
    hint?: string;
    className?: string;
}

/** A single figure with its label and comparison text. */
export const StatCard: React.FC<MetricProps> = ({ label, value, hint, className }) => (
    <div className={cn('panel px-5 py-4', className)}>
        <p className="label">{label}</p>
        <p className="stat-value mt-3">{value}</p>
        {hint && <p className="mt-2 text-[12px] text-ink-muted">{hint}</p>}
    </div>
);

interface PanelHeaderProps {
    title: string;
    description?: string;
    action?: React.ReactNode;
    className?: string;
}

export const PanelHeader: React.FC<PanelHeaderProps> = ({ title, description, action, className }) => (
    <div
        className={cn(
            'flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4 sm:px-6',
            className
        )}
    >
        <div className="min-w-0">
            <h2 className="section-title">{title}</h2>
            {description && <p className="mt-0.5 text-[12.5px] text-ink-muted">{description}</p>}
        </div>
        {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
);

export const Panel: React.FC<{ children: React.ReactNode; className?: string }> = ({
    children,
    className,
}) => <div className={cn('panel', className)}>{children}</div>;

interface EmptyStateProps {
    icon: React.ElementType;
    title: string;
    description?: string;
    action?: React.ReactNode;
    className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
    icon: Icon,
    title,
    description,
    action,
    className,
}) => (
    <div className={cn('empty-state', className)}>
        <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-full border border-line bg-white text-ink-muted">
            <Icon className="h-[18px] w-[18px]" strokeWidth={1.6} />
        </span>
        <p className="text-[13.5px] font-medium text-ink">{title}</p>
        {description && <p className="mt-1 max-w-sm text-[12.5px] text-ink-muted">{description}</p>}
        {action && <div className="mt-4">{action}</div>}
    </div>
);

export const SectionHeading: React.FC<{
    title: string;
    hint?: string;
    action?: React.ReactNode;
    className?: string;
}> = ({ title, hint, action, className }) => (
    <div className={cn('flex items-end justify-between gap-4', className)}>
        <div>
            <span className="evidence-rule" aria-hidden="true" />
            <h2 className="mt-2 text-[16px] font-medium tracking-tight text-ink">{title}</h2>
            {hint && <p className="mt-0.5 text-[12.5px] text-ink-muted">{hint}</p>}
        </div>
        {action}
    </div>
);
