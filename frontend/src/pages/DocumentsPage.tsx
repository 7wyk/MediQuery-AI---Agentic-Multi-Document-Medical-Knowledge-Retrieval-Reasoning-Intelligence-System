import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    AlertCircle,
    CheckCircle2,
    FileSearch,
    FileText,
    Info,
    RefreshCw,
    Search,
    Trash2,
    Upload,
} from 'lucide-react';
import Shell from '../components/layout/Shell';
import PageHeader from '../components/layout/PageHeader';
import { Badge, EmptyState, Panel } from '../components/ui/Primitives';
import Modal from '../components/ui/Modal';
import documentsService, { Document, DocumentStatus, UploadRejection } from '../services/documents.service';
import { documentStatusMeta } from '../lib/documentStatus';
import { cn, formatDate, formatFileSize } from '../lib/utils';

const ACCEPTED_TYPES = '.pdf,.docx,.xlsx,.csv,.txt,.jpg,.jpeg,.png';

const FILTERS: Array<{ value: 'all' | DocumentStatus; label: string }> = [
    { value: 'all', label: 'All' },
    { value: 'completed', label: 'Indexed' },
    { value: 'processing', label: 'Processing' },
    { value: 'rejected', label: 'Not medical' },
    { value: 'failed', label: 'Failed' },
];

const DocumentsPage: React.FC = () => {
    const [documents, setDocuments] = useState<Document[]>([]);
    const [loading, setLoading] = useState(true);
    const [uploading, setUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);
    const [rejected, setRejected] = useState<UploadRejection[]>([]);
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');
    const [dragging, setDragging] = useState(false);
    const [query, setQuery] = useState('');
    const [statusFilter, setStatusFilter] = useState<'all' | DocumentStatus>('all');
    const [pendingDelete, setPendingDelete] = useState<Document | null>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const pollRef = useRef<number | null>(null);

    const fetchDocuments = useCallback(async () => {
        try {
            const data = await documentsService.list();
            setDocuments(data.documents);
        } catch {
            setError('Could not load your documents. Check the backend connection and try again.');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchDocuments();
    }, [fetchDocuments]);

    const hasActiveProcessing = documents.some(
        (doc) => doc.status === 'queued' || doc.status === 'processing'
    );

    useEffect(() => {
        if (!hasActiveProcessing) {
            if (pollRef.current) {
                window.clearInterval(pollRef.current);
                pollRef.current = null;
            }
            return;
        }
        if (pollRef.current) return;
        pollRef.current = window.setInterval(() => {
            fetchDocuments();
        }, 3000);
        return () => {
            if (pollRef.current) {
                window.clearInterval(pollRef.current);
                pollRef.current = null;
            }
        };
    }, [hasActiveProcessing, fetchDocuments]);

    const uploadFiles = async (files: FileList | File[]) => {
        const list = Array.from(files);
        if (list.length === 0) return;

        setUploading(true);
        setUploadProgress(0);
        setRejected([]);
        setNotice('');
        setError('');

        try {
            const response = await documentsService.upload(list as unknown as FileList, (progress) => {
                setUploadProgress(progress);
            });
            setRejected(response.rejected || []);
            setNotice(response.message || '');
            await fetchDocuments();
        } catch (uploadError: any) {
            setError(uploadError.response?.data?.detail || 'Upload failed. Try again.');
        } finally {
            setUploading(false);
            setUploadProgress(0);
            if (inputRef.current) inputRef.current.value = '';
        }
    };

    const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
        if (event.target.files) uploadFiles(event.target.files);
    };

    const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
        event.preventDefault();
        setDragging(false);
        if (event.dataTransfer.files?.length) uploadFiles(event.dataTransfer.files);
    };

    const handleDelete = async () => {
        if (!pendingDelete) return;
        const target = pendingDelete;
        setPendingDelete(null);
        try {
            await documentsService.delete(target.id);
            await fetchDocuments();
        } catch (deleteError: any) {
            setError(deleteError.response?.data?.detail || 'Failed to delete the document.');
        }
    };

    const handleReindex = async (docId: string) => {
        setError('');
        try {
            await documentsService.reindex(docId);
            await fetchDocuments();
        } catch (reindexError: any) {
            setError(reindexError.response?.data?.detail || 'Failed to queue re-indexing.');
        }
    };

    const filtered = useMemo(() => {
        const term = query.trim().toLowerCase();
        return documents.filter((doc) => {
            const matchesStatus = statusFilter === 'all' || doc.status === statusFilter;
            const matchesQuery = !term || doc.filename.toLowerCase().includes(term);
            return matchesStatus && matchesQuery;
        });
    }, [documents, query, statusFilter]);

    const counts = useMemo(() => {
        const base: Record<string, number> = { all: documents.length };
        documents.forEach((doc) => {
            base[doc.status] = (base[doc.status] ?? 0) + 1;
        });
        return base;
    }, [documents]);

    return (
        <Shell>
            <PageHeader
                meta="Document library"
                title="Your medical documents"
                description="Every upload is screened for medical relevance, then split into passages and indexed for citation-level retrieval."
                actions={
                    <>
                        <button
                            type="button"
                            onClick={() => inputRef.current?.click()}
                            className="btn-primary"
                            disabled={uploading}
                        >
                            <Upload className="h-4 w-4" strokeWidth={1.75} />
                            Upload files
                        </button>
                        <span className="text-[12px] text-ink-soft">
                            {documents.length} document{documents.length === 1 ? '' : 's'} in this workspace
                        </span>
                    </>
                }
            />

            <div className="mx-auto max-w-shell px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
                {error && (
                    <div className="alert-danger mb-4 flex items-start justify-between gap-3">
                        <span className="flex items-start gap-2">
                            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.75} />
                            {error}
                        </span>
                        <button
                            type="button"
                            onClick={() => setError('')}
                            className="text-[12px] font-medium underline"
                        >
                            Dismiss
                        </button>
                    </div>
                )}

                <div className="grid gap-4 lg:grid-cols-3">
                    <Panel className="order-2 min-w-0 overflow-hidden lg:order-1 lg:col-span-2">
                        <div className="border-b border-line px-5 py-4 sm:px-6">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                                <div>
                                    <span className="evidence-rule" aria-hidden="true" />
                                    <h2 className="mt-1.5 text-[15px] font-medium text-ink">
                                        Library
                                    </h2>
                                </div>
                                <label className="relative w-full sm:w-64">
                                    <span className="sr-only">Search documents</span>
                                    <Search
                                        className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted"
                                        strokeWidth={1.75}
                                    />
                                    <input
                                        type="search"
                                        value={query}
                                        onChange={(event) => setQuery(event.target.value)}
                                        placeholder="Search by filename"
                                        className="input pl-9"
                                    />
                                </label>
                            </div>

                            <div className="no-scrollbar mt-3 flex gap-1.5 overflow-x-auto pb-0.5">
                                {FILTERS.map((filter) => {
                                    const active = statusFilter === filter.value;
                                    const count = counts[filter.value] ?? 0;
                                    return (
                                        <button
                                            key={filter.value}
                                            type="button"
                                            onClick={() => setStatusFilter(filter.value)}
                                            className={cn('chip transition-colors', active && 'chip-active')}
                                            aria-pressed={active}
                                        >
                                            {filter.label}
                                            <span className="tabular text-[11px] opacity-70">{count}</span>
                                        </button>
                                    );
                                })}
                            </div>
                        </div>

                        {loading ? (
                            <div className="space-y-3 p-5 sm:p-6">
                                {[0, 1, 2, 3].map((row) => (
                                    <div key={row} className="skeleton h-16 w-full" />
                                ))}
                            </div>
                        ) : filtered.length === 0 ? (
                            <div className="p-5 sm:p-6">
                                <EmptyState
                                    icon={FileText}
                                    title={documents.length === 0 ? 'Your library is empty' : 'No documents match'}
                                    description={
                                        documents.length === 0
                                            ? 'Upload a guideline, paper, protocol or scan. Text, tables and figures are extracted for retrieval.'
                                            : 'Adjust the search term or choose another status filter.'
                                    }
                                    action={
                                        documents.length === 0 ? (
                                            <button
                                                type="button"
                                                onClick={() => inputRef.current?.click()}
                                                className="btn-primary btn-sm"
                                            >
                                                <Upload className="h-4 w-4" strokeWidth={1.75} />
                                                Upload files
                                            </button>
                                        ) : (
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    setQuery('');
                                                    setStatusFilter('all');
                                                }}
                                                className="btn-secondary btn-sm"
                                            >
                                                Clear filters
                                            </button>
                                        )
                                    }
                                />
                            </div>
                        ) : (
                            <ul className="divide-y divide-line">
                                {filtered.map((doc) => {
                                    const status = documentStatusMeta(doc.status);
                                    const working = doc.status === 'queued' || doc.status === 'processing';
                                    return (
                                        <li key={doc.id} className="px-5 py-4 sm:px-6">
                                            <div className="flex flex-wrap items-start gap-3">
                                                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[9px] border border-line bg-paper-wash text-ink-muted">
                                                    <FileText className="h-4 w-4" strokeWidth={1.7} />
                                                </span>

                                                <div className="min-w-0 flex-1">
                                                    <p className="truncate text-[13.5px] font-medium text-ink">
                                                        {doc.filename}
                                                    </p>
                                                    <p className="meta mt-0.5">
                                                        {formatFileSize(doc.file_size)} ·{' '}
                                                        {formatDate(doc.upload_date)}
                                                        {doc.page_count > 0 && ` · ${doc.page_count} pages`}
                                                        {doc.chunk_count > 0 &&
                                                            ` · ${doc.chunk_count} indexed passages`}
                                                    </p>

                                                    {working && (
                                                        <div className="mt-2 max-w-sm">
                                                            <div className="mb-1 flex items-center justify-between text-[11px] text-ink-muted">
                                                                <span className="capitalize">
                                                                    {doc.stage?.replace(/_/g, ' ') || 'waiting'}
                                                                </span>
                                                                <span className="tabular">{doc.progress}%</span>
                                                            </div>
                                                            <div className="h-1.5 overflow-hidden rounded-full bg-sky-100">
                                                                <div
                                                                    className="h-full rounded-full bg-royal transition-[width] duration-300"
                                                                    style={{ width: `${doc.progress}%` }}
                                                                />
                                                            </div>
                                                        </div>
                                                    )}

                                                    {doc.rejection_reason && (
                                                        <p className="mt-2 rounded-md border border-warning/30 bg-warning-soft px-2.5 py-1.5 text-[12px] text-warning-ink">
                                                            {doc.rejection_reason}
                                                        </p>
                                                    )}
                                                    {doc.error_message && (
                                                        <p className="mt-2 rounded-md border border-danger/30 bg-danger-soft px-2.5 py-1.5 text-[12px] text-danger-ink">
                                                            {doc.error_message}
                                                        </p>
                                                    )}
                                                </div>

                                                <div className="ml-auto flex shrink-0 items-center gap-1">
                                                    <Badge tone={status.tone}>{status.label}</Badge>
                                                    <button
                                                        type="button"
                                                        onClick={() => handleReindex(doc.id)}
                                                        className="btn-icon"
                                                        title="Re-index document"
                                                        aria-label={`Re-index ${doc.filename}`}
                                                        disabled={working}
                                                    >
                                                        <RefreshCw className="h-4 w-4" strokeWidth={1.75} />
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => setPendingDelete(doc)}
                                                        className="btn-icon text-danger-ink hover:bg-danger-soft hover:text-danger-ink"
                                                        title="Delete document"
                                                        aria-label={`Delete ${doc.filename}`}
                                                    >
                                                        <Trash2 className="h-4 w-4" strokeWidth={1.75} />
                                                    </button>
                                                </div>
                                            </div>
                                        </li>
                                    );
                                })}
                            </ul>
                        )}
                    </Panel>

                    <div className="order-1 grid min-w-0 gap-4 lg:order-2">
                        <Panel className="panel-body">
                            <span className="evidence-rule" aria-hidden="true" />
                            <h2 className="mt-2 text-[15px] font-medium text-ink">Add documents</h2>
                            <p className="mt-1 text-[12.5px] leading-relaxed text-ink-muted">
                                PDF, DOCX, XLSX, CSV, TXT and scanned images up to 25 MB each.
                            </p>

                            <div
                                onDragOver={(event) => {
                                    event.preventDefault();
                                    setDragging(true);
                                }}
                                onDragLeave={() => setDragging(false)}
                                onDrop={handleDrop}
                                className={cn(
                                    'mt-4 rounded-input border border-dashed px-4 py-6 text-center transition-colors duration-150',
                                    dragging
                                        ? 'border-royal bg-royal-soft'
                                        : 'border-sky-300 bg-sky-50/70'
                                )}
                            >
                                <Upload
                                    className="mx-auto h-6 w-6 text-royal/70"
                                    strokeWidth={1.6}
                                />
                                <p className="mt-2 text-[13px] font-medium text-ink">
                                    Drop files to upload
                                </p>
                                <p className="mt-0.5 text-[11.5px] text-ink-muted">or</p>
                                <button
                                    type="button"
                                    onClick={() => inputRef.current?.click()}
                                    disabled={uploading}
                                    className="btn-secondary btn-sm mt-2"
                                >
                                    Browse files
                                </button>
                                <input
                                    ref={inputRef}
                                    type="file"
                                    multiple
                                    accept={ACCEPTED_TYPES}
                                    onChange={handleFileUpload}
                                    disabled={uploading}
                                    className="hidden"
                                />
                            </div>

                            {uploading && (
                                <div className="mt-4">
                                    <div className="mb-1.5 flex items-center justify-between text-[12px]">
                                        <span className="text-ink-soft">Uploading</span>
                                        <span className="tabular font-medium text-ink">
                                            {uploadProgress}%
                                        </span>
                                    </div>
                                    <div className="h-1.5 overflow-hidden rounded-full bg-sky-100">
                                        <div
                                            className="h-full rounded-full bg-royal transition-[width] duration-300"
                                            style={{ width: `${uploadProgress}%` }}
                                        />
                                    </div>
                                </div>
                            )}

                            {notice && (
                                <div className="alert-info mt-4 flex items-start gap-2">
                                    <Info className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.75} />
                                    {notice}
                                </div>
                            )}

                            {rejected.length > 0 && (
                                <div className="mt-3 rounded-input border border-warning/30 bg-warning-soft px-3 py-2.5">
                                    <p className="text-[12px] font-medium text-warning-ink">
                                        Files not accepted
                                    </p>
                                    <ul className="mt-1 space-y-1 text-[11.5px] text-warning-ink">
                                        {rejected.map((item, index) => (
                                            <li key={`${item.filename}-${index}`}>
                                                <span className="font-medium">{item.filename}</span>: {item.reason}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </Panel>

                        <Panel className="panel-body">
                            <h2 className="text-[13.5px] font-medium text-ink">What happens next</h2>
                            <ol className="mt-3 space-y-3">
                                {[
                                    { icon: CheckCircle2, text: 'Screened for medical relevance' },
                                    { icon: FileSearch, text: 'Parsed into text, tables and figures' },
                                    { icon: FileText, text: 'Indexed into citable passages' },
                                ].map((step) => (
                                    <li key={step.text} className="flex items-start gap-2.5">
                                        <step.icon
                                            className="mt-0.5 h-4 w-4 shrink-0 text-ink-muted"
                                            strokeWidth={1.7}
                                        />
                                        <span className="text-[12.5px] leading-relaxed text-ink-soft">
                                            {step.text}
                                        </span>
                                    </li>
                                ))}
                            </ol>
                        </Panel>
                    </div>
                </div>
            </div>

            <Modal
                open={pendingDelete !== null}
                title="Delete this document"
                description={
                    pendingDelete
                        ? `"${pendingDelete.filename}" and all of its indexed passages will be removed. Answers will no longer cite it.`
                        : undefined
                }
                onClose={() => setPendingDelete(null)}
                footer={
                    <>
                        <button
                            type="button"
                            onClick={() => setPendingDelete(null)}
                            className="btn-secondary btn-sm"
                        >
                            Keep document
                        </button>
                        <button
                            type="button"
                            onClick={handleDelete}
                            className="btn-sm inline-flex items-center gap-1.5 rounded-btn bg-danger-ink px-3 text-[13px] font-medium text-white transition-colors hover:bg-danger"
                        >
                            <Trash2 className="h-4 w-4" strokeWidth={1.75} />
                            Delete
                        </button>
                    </>
                }
            />
        </Shell>
    );
};

export default DocumentsPage;
