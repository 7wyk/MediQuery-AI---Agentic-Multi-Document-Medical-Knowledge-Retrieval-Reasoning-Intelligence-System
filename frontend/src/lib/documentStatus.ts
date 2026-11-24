import type { DocumentStatus } from '../services/documents.service';
import type { Tone } from '../components/ui/Primitives';

export const documentStatusMeta = (status: DocumentStatus): { label: string; tone: Tone } => {
    switch (status) {
        case 'completed':
            return { label: 'Indexed', tone: 'success' };
        case 'processing':
            return { label: 'Processing', tone: 'info' };
        case 'queued':
            return { label: 'Queued', tone: 'neutral' };
        case 'rejected':
            return { label: 'Not medical', tone: 'warning' };
        default:
            return { label: 'Failed', tone: 'danger' };
    }
};
