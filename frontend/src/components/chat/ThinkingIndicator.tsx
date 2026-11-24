import React, { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';

const STAGES = [
    'Reviewing your medical documents...',
    'Checking relevant evidence...',
    'Preparing your answer...',
];

const ThinkingIndicator: React.FC<{ mode: 'standard' | 'agentic' }> = ({ mode }) => {
    const [stage, setStage] = useState(0);

    useEffect(() => {
        const timer = window.setInterval(() => {
            setStage((current) => Math.min(current + 1, STAGES.length - 1));
        }, 2600);
        return () => window.clearInterval(timer);
    }, []);

    return (
        <div className="flex items-center gap-2.5 py-1" role="status" aria-live="polite">
            <Loader2 className="h-4 w-4 animate-spin text-royal" strokeWidth={2} />
            <span className="text-[13.5px] text-ink-soft">{STAGES[stage]}</span>
            <span className="text-[11.5px] text-ink-muted">
                {mode === 'agentic' ? 'Agentic' : 'Standard'}
            </span>
        </div>
    );
};

export default ThinkingIndicator;
