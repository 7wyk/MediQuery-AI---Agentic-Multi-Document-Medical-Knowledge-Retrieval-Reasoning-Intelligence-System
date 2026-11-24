import React, { useMemo, useState } from 'react';
import { ChevronDown, FileSearch } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { AgentMetadata } from '../../services/chat.service';

interface AnswerProvenanceProps {
    metadata: AgentMetadata;
}

const percent = (value?: number | null) =>
    typeof value === 'number' ? `${Math.round(value * 100)}%` : null;

/**
 * A quiet, opt-in explanation of how the answer was produced.
 *
 * Retrieval attempts, coverage and latency are real but belong in a disclosure
 * people open deliberately - never in the always-visible chat surface.
 */
const AnswerProvenance: React.FC<AnswerProvenanceProps> = ({ metadata }) => {
    const [open, setOpen] = useState(false);

    const summary = useMemo(() => {
        const lines: string[] = [];
        const passages = metadata.passages_retained || metadata.documents_retrieved || 0;

        if (passages > 0) {
            lines.push(
                `Reviewed ${passages} ${passages === 1 ? 'passage' : 'passages'} from your uploaded documents.`
            );
        }
        if (metadata.retrieval_attempts > 1) {
            lines.push('Searched again with a refined version of your question.');
        }
        if (metadata.graph_rag_used) {
            lines.push('Cross-checked related concepts in your knowledge graph.');
        }
        if (metadata.web_search_used) {
            lines.push('Used trusted external medical sources to supplement your documents.');
        }
        if (metadata.verification_status === 'verified') {
            lines.push('Checked the statements in the answer against the retrieved passages.');
        }
        if ((metadata.evidence_outcome || '') === 'insufficient' || metadata.fallback_to_standard) {
            lines.push('The available evidence was limited, so the answer stays cautious.');
        }
        if (lines.length === 0) {
            lines.push('Answered from the passages retrieved out of your uploaded documents.');
        }
        return lines;
    }, [metadata]);

    const details: Array<{ label: string; value: string }> = [
        { label: 'Search attempts', value: String(metadata.retrieval_attempts ?? 0) },
        {
            label: 'Passages retained',
            value: String(metadata.passages_retained ?? metadata.documents_retrieved ?? 0),
        },
    ];
    const coverage = percent(metadata.evidence_coverage);
    if (coverage) details.push({ label: 'Evidence coverage', value: coverage });
    if (typeof metadata.latency_ms?.total_ms === 'number') {
        details.push({ label: 'Response time', value: `${Math.round(metadata.latency_ms.total_ms)} ms` });
    }

    return (
        <div className="w-full">
            <button
                type="button"
                onClick={() => setOpen((value) => !value)}
                aria-expanded={open}
                className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-ink-muted transition-colors duration-150 hover:text-ink"
            >
                <FileSearch className="h-3.5 w-3.5" strokeWidth={1.75} />
                How this answer was generated
                <ChevronDown
                    className={cn('h-3.5 w-3.5 transition-transform duration-200', open && 'rotate-180')}
                    strokeWidth={1.75}
                />
            </button>

            {open && (
                <div className="mt-2.5 animate-fade-in rounded-input border border-line bg-paper-wash/60 px-3.5 py-3">
                    <ul className="space-y-1.5">
                        {summary.map((line) => (
                            <li key={line} className="flex gap-2 text-[12.5px] leading-relaxed text-ink-soft">
                                <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-royal/50" aria-hidden="true" />
                                {line}
                            </li>
                        ))}
                    </ul>

                    <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-line pt-3 sm:grid-cols-4">
                        {details.map((detail) => (
                            <div key={detail.label}>
                                <dt className="text-[11px] text-ink-muted">{detail.label}</dt>
                                <dd className="tabular text-[12.5px] font-medium text-ink">{detail.value}</dd>
                            </div>
                        ))}
                    </dl>
                </div>
            )}
        </div>
    );
};

export default AnswerProvenance;
