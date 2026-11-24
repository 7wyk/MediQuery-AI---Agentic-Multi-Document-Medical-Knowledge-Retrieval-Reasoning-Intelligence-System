import React, { useEffect, useRef } from 'react';
import { ArrowUp, Workflow, Zap } from 'lucide-react';
import { cn } from '../../lib/utils';

export type RagMode = 'standard' | 'agentic';

interface ChatComposerProps {
    value: string;
    onChange: (value: string) => void;
    onSubmit: () => void;
    loading: boolean;
    disabled?: boolean;
    mode: RagMode;
    onModeChange: (mode: RagMode) => void;
    allowWeb: boolean;
    onAllowWebChange: (allow: boolean) => void;
}

const MODES: Array<{ value: RagMode; label: string; icon: React.ElementType }> = [
    { value: 'standard', label: 'Standard', icon: Zap },
    { value: 'agentic', label: 'Agentic', icon: Workflow },
];

const ChatComposer: React.FC<ChatComposerProps> = ({
    value,
    onChange,
    onSubmit,
    loading,
    disabled = false,
    mode,
    onModeChange,
    allowWeb,
    onAllowWebChange,
}) => {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const blocked = loading || disabled;

    useEffect(() => {
        const node = textareaRef.current;
        if (!node) return;
        node.style.height = 'auto';
        // Empty composer returns to its natural single-line height.
        node.style.height = value ? `${Math.min(node.scrollHeight, 168)}px` : '';
    }, [value]);

    const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            if (!blocked && value.trim()) onSubmit();
        }
    };

    return (
        <form
            onSubmit={(event) => {
                event.preventDefault();
                if (!blocked && value.trim()) onSubmit();
            }}
            className="px-3 pb-2.5 pt-3 sm:px-5 sm:pb-3"
        >
            <div className="rounded-panel border border-line bg-white px-2.5 pb-2 pt-2 shadow-card transition-colors focus-within:border-sky-300 focus-within:ring-2 focus-within:ring-royal/10">
                <label htmlFor="chat-input" className="sr-only">
                    Ask a question about your documents
                </label>
                <div className="flex items-end gap-1.5">
                    <textarea
                        id="chat-input"
                        ref={textareaRef}
                        rows={1}
                        value={value}
                        onChange={(event) => onChange(event.target.value)}
                        onKeyDown={handleKeyDown}
                        disabled={blocked}
                        placeholder="Ask about a guideline, dosage, table or finding in your documents"
                        className="max-h-[168px] w-full flex-1 resize-none border-0 bg-transparent px-1.5 py-1 text-[14px] leading-relaxed text-ink placeholder:text-ink-muted focus:outline-none disabled:text-ink-muted"
                    />
                    <button
                        type="submit"
                        disabled={blocked || !value.trim()}
                        className="btn-primary mb-0.5 h-9 w-9 shrink-0 rounded-btn px-0"
                        aria-label="Send question"
                    >
                        <ArrowUp className="h-4 w-4" strokeWidth={2} />
                    </button>
                </div>

                <div className="mt-1 flex flex-wrap items-center gap-2">
                    <div
                        className="inline-flex rounded-[9px] border border-line bg-paper-wash p-0.5"
                        role="group"
                        aria-label="Search mode"
                    >
                        {MODES.map((item) => (
                            <button
                                key={item.value}
                                type="button"
                                onClick={() => onModeChange(item.value)}
                                aria-pressed={mode === item.value}
                                className={cn(
                                    'inline-flex h-7 items-center gap-1.5 rounded-[7px] px-2 text-[12px] font-medium transition-colors duration-150',
                                    mode === item.value
                                        ? 'bg-white text-royal shadow-card'
                                        : 'text-ink-muted hover:text-ink'
                                )}
                            >
                                <item.icon className="h-3.5 w-3.5" strokeWidth={1.75} />
                                {item.label}
                            </button>
                        ))}
                    </div>

                    <label className="flex cursor-pointer select-none items-center gap-2 text-[12px] text-ink-muted">
                        <span
                            className={cn(
                                'relative h-[18px] w-[30px] rounded-full transition-colors duration-150',
                                allowWeb ? 'bg-royal' : 'bg-sky-200'
                            )}
                            aria-hidden="true"
                        >
                            <span
                                className={cn(
                                    'absolute top-[3px] h-3 w-3 rounded-full bg-white transition-[left] duration-150',
                                    allowWeb ? 'left-[15px]' : 'left-[3px]'
                                )}
                            />
                        </span>
                        <input
                            type="checkbox"
                            className="sr-only"
                            checked={allowWeb}
                            onChange={(event) => onAllowWebChange(event.target.checked)}
                        />
                        Web sources
                    </label>

                    <span className="ml-auto hidden text-[11.5px] text-ink-muted sm:block">
                        Shift + Enter for a new line
                    </span>
                </div>
            </div>
            <p className="mt-2 px-1 text-[11px] text-ink-muted">
                Answers are limited to your uploaded documents and cited pages. Verify before
                clinical use.
            </p>
        </form>
    );
};

export default ChatComposer;
