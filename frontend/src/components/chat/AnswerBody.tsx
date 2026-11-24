import React, { useMemo } from 'react';
import { cn } from '../../lib/utils';
import type { SourceCitation } from '../../services/chat.service';

interface AnswerBodyProps {
    content: string;
    sources?: SourceCitation[];
    activeIndex?: number | null;
    onSelectSource?: (index: number) => void;
    className?: string;
}

type Block =
    | { kind: 'paragraph'; text: string }
    | { kind: 'heading'; level: number; text: string }
    | { kind: 'list'; ordered: boolean; items: string[] }
    | { kind: 'quote'; text: string }
    | { kind: 'code'; text: string }
    | { kind: 'table'; header: string[]; rows: string[][] }
    | { kind: 'rule' };

const LIST_BULLET = /^[-*•]\s+(.*)$/;
const LIST_NUMBER = /^\d+[.)]\s+(.*)$/;
// Models often emit non-breaking hyphens (U+2011) as list bullets.
const normaliseDashes = (value: string) => value.replace(/\u2011/g, '-');
const TABLE_DIVIDER = /^\|?[\s:|-]+\|?$/;
const HEADING = /^(#{1,4})\s+(.*)$/;
const RULE = /^(-{3,}|\*{3,}|_{3,})$/;

/**
 * Models sometimes emit sub-bullets inline: "- item - **next item**".
 * Splitting on that separator keeps those answers readable as lists.
 */
const INLINE_BULLET = /\s+[-\u2011]\s+(?=\*\*|["\u201cA-Z0-9])/;

const expandBullets = (items: string[]): string[] =>
    items.flatMap((item) =>
        item
            .split(INLINE_BULLET)
            .map((part) => part.trim())
            .filter((part) => part.length > 0)
    );

const splitCells = (line: string): string[] =>
    line
        .trim()
        .replace(/^\|/, '')
        .replace(/\|$/, '')
        .split('|')
        .map((cell) => cell.trim());

/** Small, dependency-free block parser for the markdown the RAG prompt produces. */
export const parseAnswerBlocks = (source: string): Block[] => {
    const lines = source.replace(/\r\n/g, '\n').split('\n');
    const blocks: Block[] = [];
    let index = 0;

    while (index < lines.length) {
        const line = lines[index].trim();
        const probe = normaliseDashes(line);

        if (!line) {
            index += 1;
            continue;
        }

        if (line.startsWith('```')) {
            const body: string[] = [];
            index += 1;
            while (index < lines.length && !lines[index].trim().startsWith('```')) {
                body.push(lines[index]);
                index += 1;
            }
            index += 1;
            blocks.push({ kind: 'code', text: body.join('\n') });
            continue;
        }

        const heading = HEADING.exec(probe);
        if (heading) {
            blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2].trim() });
            index += 1;
            continue;
        }

        if (RULE.test(probe)) {
            blocks.push({ kind: 'rule' });
            index += 1;
            continue;
        }

        const nextLine = normaliseDashes(lines[index + 1]?.trim() ?? '');
        if (probe.includes('|') && nextLine.includes('-') && TABLE_DIVIDER.test(nextLine)) {
            const header = splitCells(line);
            const rows: string[][] = [];
            index += 2;
            while (index < lines.length && lines[index].trim().includes('|')) {
                rows.push(splitCells(lines[index]));
                index += 1;
            }
            blocks.push({ kind: 'table', header, rows });
            continue;
        }

        if (LIST_BULLET.test(probe) || LIST_NUMBER.test(probe)) {
            const ordered = LIST_NUMBER.test(probe);
            const marker = ordered ? /^\d+[.)]\s+/ : /^[-*•]\s+/;
            const items: string[] = [];
            while (index < lines.length) {
                const raw = lines[index].trim();
                const candidate = normaliseDashes(raw);
                if (!(ordered ? LIST_NUMBER.test(candidate) : LIST_BULLET.test(candidate))) {
                    break;
                }
                items.push(raw.replace(marker, '').trim());
                index += 1;
            }
            blocks.push({ kind: 'list', ordered, items: ordered ? items : expandBullets(items) });
            continue;
        }

        if (probe.startsWith('>')) {
            const body: string[] = [];
            while (index < lines.length && lines[index].trim().startsWith('>')) {
                body.push(lines[index].trim().replace(/^>\s?/, ''));
                index += 1;
            }
            blocks.push({ kind: 'quote', text: body.join(' ') });
            continue;
        }

        const paragraph: string[] = [line];
        index += 1;
        while (index < lines.length) {
            const candidate = lines[index].trim();
            const probeCandidate = normaliseDashes(candidate);
            if (
                !candidate ||
                probeCandidate.startsWith('```') ||
                HEADING.test(probeCandidate) ||
                RULE.test(probeCandidate) ||
                probeCandidate.startsWith('>') ||
                LIST_BULLET.test(probeCandidate) ||
                LIST_NUMBER.test(probeCandidate)
            ) {
                break;
            }
            paragraph.push(candidate);
            index += 1;
        }
        blocks.push({ kind: 'paragraph', text: paragraph.join(' ') });
    }

    return blocks;
};

const INLINE_SOURCE =
    /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\[\d+(?:\s*,\s*\d+)*\]|【\d+(?:\s*,\s*\d+)*】|\*[^*\n]+\*)/.source;

const AnswerBody: React.FC<AnswerBodyProps> = ({
    content,
    sources = [],
    activeIndex,
    onSelectSource,
    className,
}) => {
    const known = useMemo(() => new Set(sources.map((source) => source.index)), [sources]);
    const blocks = useMemo(() => parseAnswerBlocks(content), [content]);

    const renderInline = (text: string, keyPrefix: string): React.ReactNode[] => {
        const nodes: React.ReactNode[] = [];
        // A fresh matcher per call: recursive bold/italic rendering must not
        // share (and reset) the caller's lastIndex.
        const pattern = new RegExp(INLINE_SOURCE, 'g');
        let lastIndex = 0;
        let match: RegExpExecArray | null;
        let tokenIndex = 0;

        while ((match = pattern.exec(text)) !== null) {
            if (match.index > lastIndex) {
                nodes.push(text.slice(lastIndex, match.index));
            }
            const token = match[0];
            const key = `${keyPrefix}-${tokenIndex}`;

            if (token.startsWith('**') || token.startsWith('__')) {
                nodes.push(
                    <strong key={key} className="font-semibold text-ink">
                        {renderInline(token.slice(2, -2), key)}
                    </strong>
                );
            } else if (token.startsWith('`')) {
                nodes.push(
                    <code
                        key={key}
                        className="rounded-[5px] border border-line bg-paper-wash px-1 py-0.5 font-mono text-[12.5px] text-ink"
                    >
                        {token.slice(1, -1)}
                    </code>
                );
            } else if (token.startsWith('*')) {
                nodes.push(
                    <em key={key} className="italic">
                        {renderInline(token.slice(1, -1), key)}
                    </em>
                );
            } else if (token.startsWith('[') && token.includes('](')) {
                const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token);
                if (link) {
                    nodes.push(
                        <a
                            key={key}
                            href={link[2]}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="font-medium text-royal underline decoration-royal/30 underline-offset-2 hover:decoration-royal"
                        >
                            {link[1]}
                        </a>
                    );
                } else {
                    nodes.push(token);
                }
            } else if (/^([\[【])\d/.test(token)) {
                const indexes = token
                    .slice(1, -1)
                    .split(',')
                    .map((value) => Number(value.trim()))
                    .filter((value) => Number.isFinite(value));

                indexes.forEach((citation, position) => {
                    if (!known.has(citation)) {
                        // The answer references a marker the backend did not
                        // return evidence for: show it quietly, never link it.
                        nodes.push(
                            <span
                                key={`${key}-raw-${position}`}
                                title="No source was returned for this reference"
                                aria-label={`Reference ${citation} has no source in this answer`}
                                className="mx-0.5 inline-flex h-[19px] min-w-[19px] items-center justify-center rounded-[5px] border border-line bg-paper-wash px-1 align-[1px] text-[11px] font-medium leading-none text-ink-muted"
                            >
                                {citation}
                            </span>
                        );
                        return;
                    }
                    nodes.push(
                        <button
                            key={`${key}-${position}`}
                            type="button"
                            onClick={() => onSelectSource?.(citation)}
                            className={cn(
                                'ref mx-0.5 align-[1px]',
                                activeIndex === citation && 'ref-active'
                            )}
                            aria-label={`Show source ${citation}`}
                            title={`Source ${citation}`}
                        >
                            {citation}
                        </button>
                    );
                });
            }

            lastIndex = match.index + token.length;
            tokenIndex += 1;
        }

        if (lastIndex < text.length) {
            nodes.push(text.slice(lastIndex));
        }
        return nodes;
    };

    return (
        <div className={cn('text-[14.5px] leading-[1.75] text-ink-soft', className)}>
            {blocks.map((block, blockIndex) => {
                const key = `block-${blockIndex}`;
                switch (block.kind) {
                    case 'heading': {
                        const size =
                            block.level <= 1
                                ? 'text-[18px]'
                                : block.level === 2
                                  ? 'text-[16.5px]'
                                  : 'text-[14.5px]';
                        return (
                            <h3
                                key={key}
                                className={cn(
                                    'mt-5 font-medium tracking-tight text-ink first:mt-0',
                                    size
                                )}
                            >
                                {renderInline(block.text, key)}
                            </h3>
                        );
                    }
                    case 'list':
                        return block.ordered ? (
                            <ol
                                key={key}
                                className="mt-3 list-decimal space-y-1.5 pl-5 marker:text-[13px] marker:text-ink-muted first:mt-0"
                            >
                                {block.items.map((item, itemIndex) => (
                                    <li key={`${key}-${itemIndex}`} className="pl-1">
                                        {renderInline(item, `${key}-${itemIndex}`)}
                                    </li>
                                ))}
                            </ol>
                        ) : (
                            <ul
                                key={key}
                                className="mt-3 list-disc space-y-1.5 pl-5 marker:text-royal/50 first:mt-0"
                            >
                                {block.items.map((item, itemIndex) => (
                                    <li key={`${key}-${itemIndex}`} className="pl-1">
                                        {renderInline(item, `${key}-${itemIndex}`)}
                                    </li>
                                ))}
                            </ul>
                        );
                    case 'quote':
                        return (
                            <blockquote
                                key={key}
                                className="mt-3 border-l-2 border-sky-300 pl-3 text-ink-soft first:mt-0"
                            >
                                {renderInline(block.text, key)}
                            </blockquote>
                        );
                    case 'code':
                        return (
                            <pre
                                key={key}
                                className="mt-3 overflow-x-auto rounded-input border border-line bg-paper-wash p-3 text-[12.5px] leading-relaxed text-ink first:mt-0"
                            >
                                <code>{block.text}</code>
                            </pre>
                        );
                    case 'table':
                        return (
                            <div key={key} className="mt-4 overflow-x-auto first:mt-0">
                                <table className="w-full min-w-[420px] border-collapse text-left text-[13px]">
                                    <thead>
                                        <tr>
                                            {block.header.map((cell, cellIndex) => (
                                                <th
                                                    key={`${key}-h-${cellIndex}`}
                                                    className="border-b border-line px-3 py-2 font-medium text-ink"
                                                >
                                                    {renderInline(cell, `${key}-h-${cellIndex}`)}
                                                </th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {block.rows.map((row, rowIndex) => (
                                            <tr key={`${key}-r-${rowIndex}`}>
                                                {row.map((cell, cellIndex) => (
                                                    <td
                                                        key={`${key}-r-${rowIndex}-${cellIndex}`}
                                                        className="border-b border-line/70 px-3 py-2 align-top"
                                                    >
                                                        {renderInline(
                                                            cell,
                                                            `${key}-r-${rowIndex}-${cellIndex}`
                                                        )}
                                                    </td>
                                                ))}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        );
                    case 'rule':
                        return <hr key={key} className="mt-4 border-line first:mt-0" />;
                    default:
                        return (
                            <p key={key} className="mt-3 whitespace-pre-wrap first:mt-0">
                                {renderInline(block.text, key)}
                            </p>
                        );
                }
            })}
        </div>
    );
};

export default AnswerBody;
