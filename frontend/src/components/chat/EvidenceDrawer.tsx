import React, { useEffect } from 'react';
import { X } from 'lucide-react';
import type { SourceCitation } from '../../services/chat.service';
import EvidenceRail from './EvidenceRail';

interface EvidenceDrawerProps {
    open: boolean;
    question?: string;
    sources: SourceCitation[];
    activeIndex: number | null;
    onSelect: (index: number) => void;
    onOpen: (source: SourceCitation) => void;
    onClose: () => void;
}

/**
 * Evidence overlays the conversation: it never reserves layout space, so the
 * chat keeps the full width until the reader asks to inspect the citations.
 */
const EvidenceDrawer: React.FC<EvidenceDrawerProps> = ({
    open,
    question,
    sources,
    activeIndex,
    onSelect,
    onOpen,
    onClose,
}) => {
    useEffect(() => {
        if (!open) return;
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') onClose();
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [open, onClose]);

    if (!open) return null;

    return (
        <div className="fixed inset-0 z-50 flex sm:justify-end">
            <div
                className="absolute inset-0 animate-fade-in bg-ink/25"
                onClick={onClose}
                aria-hidden="true"
            />
            <div
                role="dialog"
                aria-modal="true"
                aria-label="Cited evidence"
                className="relative mt-auto flex h-[88vh] w-full animate-rise-in flex-col overflow-hidden rounded-t-panel border border-line bg-white shadow-lift sm:mt-0 sm:h-full sm:w-[424px] sm:rounded-none sm:rounded-l-panel sm:border-y-0 sm:border-r-0"
            >
                <span
                    className="mx-auto mt-2.5 h-1 w-10 shrink-0 rounded-full bg-line sm:hidden"
                    aria-hidden="true"
                />

                <header className="flex items-start justify-between gap-3 border-b border-line px-5 pb-3.5 pt-3 sm:pt-4">
                    <div className="min-w-0">
                        <span className="evidence-rule" aria-hidden="true" />
                        <h2 className="mt-1.5 text-[14.5px] font-medium text-ink">Cited evidence</h2>
                        <p className="mt-0.5 truncate text-[12px] text-ink-muted">
                            {sources.length} source{sources.length === 1 ? '' : 's'}
                            {question ? ` · ${question}` : ''}
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="btn-icon -mr-1.5 shrink-0"
                        aria-label="Close evidence"
                    >
                        <X className="h-4 w-4" />
                    </button>
                </header>

                <EvidenceRail
                    sources={sources}
                    activeIndex={activeIndex}
                    onSelect={onSelect}
                    onOpen={onOpen}
                    showHeader={false}
                    className="min-h-0 flex-1"
                />
            </div>
        </div>
    );
};

export default EvidenceDrawer;
