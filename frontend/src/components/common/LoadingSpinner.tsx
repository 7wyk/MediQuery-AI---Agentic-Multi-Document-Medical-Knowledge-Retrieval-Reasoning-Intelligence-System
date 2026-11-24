import React from 'react';

interface LoadingSpinnerProps {
    size?: 'sm' | 'md' | 'lg';
    className?: string;
}

const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({ size = 'md', className = '' }) => {
    const sizeClasses = {
        sm: 'h-3.5 w-3.5 border-[1.5px]',
        md: 'h-6 w-6 border-2',
        lg: 'h-9 w-9 border-2',
    };

    return (
        <div className={`flex items-center justify-center ${className}`} role="status" aria-label="Loading">
            <div className={`animate-spin rounded-full border-sky-200 border-t-royal ${sizeClasses[size]}`} />
        </div>
    );
};

export const SkeletonLine: React.FC<{ width?: string; className?: string }> = ({
    width = '100%',
    className = '',
}) => <div className={`skeleton h-3 ${className}`} style={{ width }} />;

export const SkeletonCard: React.FC = () => (
    <div className="panel panel-body">
        <SkeletonLine width="40%" />
        <SkeletonLine width="70%" className="mt-4 h-6" />
        <SkeletonLine width="55%" className="mt-4" />
    </div>
);

export const SkeletonList: React.FC<{ count?: number }> = ({ count = 3 }) => (
    <>
        {Array.from({ length: count }).map((_, i) => (
            <SkeletonCard key={i} />
        ))}
    </>
);

export default LoadingSpinner;
