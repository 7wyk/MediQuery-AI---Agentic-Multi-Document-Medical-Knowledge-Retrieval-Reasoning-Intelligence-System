import React, { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import { cn } from '../../lib/utils';

interface ModalProps {
    open: boolean;
    title: string;
    description?: string;
    onClose: () => void;
    children?: React.ReactNode;
    footer?: React.ReactNode;
    className?: string;
}

const Modal: React.FC<ModalProps> = ({
    open,
    title,
    description,
    onClose,
    children,
    footer,
    className,
}) => {
    const panelRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!open) return;
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') onClose();
        };
        document.addEventListener('keydown', onKey);
        const previous = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        const first = panelRef.current?.querySelector<HTMLElement>('button, [href], input');
        first?.focus();
        return () => {
            document.removeEventListener('keydown', onKey);
            document.body.style.overflow = previous;
        };
    }, [open, onClose]);

    if (!open) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4">
            <div
                className="absolute inset-0 animate-fade-in bg-ink/25"
                onClick={onClose}
                aria-hidden="true"
            />
            <div
                ref={panelRef}
                role="dialog"
                aria-modal="true"
                aria-label={title}
                className={cn(
                    'relative w-full animate-rise-in rounded-t-panel border border-line bg-white p-5 shadow-lift sm:max-w-md sm:rounded-panel sm:p-6',
                    className
                )}
            >
                <div className="flex items-start justify-between gap-4">
                    <div>
                        <h2 className="text-[16px] font-medium text-ink">{title}</h2>
                        {description && (
                            <p className="mt-1 text-[13px] leading-relaxed text-ink-soft">{description}</p>
                        )}
                    </div>
                    <button type="button" onClick={onClose} className="btn-icon -mr-1 -mt-1" aria-label="Close">
                        <X className="h-4 w-4" />
                    </button>
                </div>
                {children && <div className="mt-4">{children}</div>}
                {footer && <div className="mt-6 flex justify-end gap-2">{footer}</div>}
            </div>
        </div>
    );
};

export default Modal;
