import React from 'react';
import { cn } from '../../lib/utils';

interface PageHeaderProps {
    title: string;
    description?: string;
    meta?: string;
    actions?: React.ReactNode;
    aside?: React.ReactNode;
    className?: string;
    children?: React.ReactNode;
}

/**
 * The soft sky plate that opens a workspace page. It carries the light-blue
 * architectural band from the design direction without touching page content.
 */
const PageHeader: React.FC<PageHeaderProps> = ({
    title,
    description,
    meta,
    actions,
    aside,
    className,
    children,
}) => (
    <section className={cn('border-b border-sky-200 bg-sky-100', className)}>
        <div className="mx-auto max-w-shell px-4 pb-7 pt-7 sm:px-6 sm:pb-9 sm:pt-9 lg:px-8">
            <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
                <div className="min-w-0">
                    {meta && (
                        <p className="flex items-center gap-2 text-[12px] font-medium text-royal/80">
                            <span className="h-[2px] w-5 rounded-full bg-royal/70" aria-hidden="true" />
                            {meta}
                        </p>
                    )}
                    <h1 className="page-title mt-2">{title}</h1>
                    {description && (
                        <p className="mt-2 max-w-2xl text-[13.5px] leading-relaxed text-ink-soft">
                            {description}
                        </p>
                    )}
                    {actions && <div className="mt-5 flex flex-wrap items-center gap-2">{actions}</div>}
                </div>
                {aside && <div className="w-full shrink-0 lg:w-auto">{aside}</div>}
            </div>
            {children}
        </div>
    </section>
);

export default PageHeader;
