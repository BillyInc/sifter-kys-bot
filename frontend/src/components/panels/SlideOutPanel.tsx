import React, { useEffect, ReactNode } from 'react';
import { X } from 'lucide-react';

interface SlideOutPanelProps {
  isOpen: boolean;
  onClose: () => void;
  direction?: 'left' | 'right';
  width?: string;
  title: string;
  children: ReactNode;
}

export default function SlideOutPanel({
  isOpen,
  onClose,
  direction = 'right',
  width = 'w-96',
  title,
  children
}: SlideOutPanelProps) {
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) onClose();
    };
    document.addEventListener('keydown', handleEsc);
    return () => document.removeEventListener('keydown', handleEsc);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 animate-fade-in"
        onClick={onClose}
      />

      <div
        className={`fixed top-0 ${direction === 'left' ? 'left-0' : 'right-0'} h-full w-full sm:${width} border-${direction === 'left' ? 'r' : 'l'} z-50 flex flex-col shadow-2xl animate-slide-in-${direction}`}
        style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)' }}
      >
        <div className="flex-shrink-0 flex items-center justify-between p-3 sm:p-4 border-b" style={{ borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}>
          <h2 className="text-base sm:text-lg font-bold truncate">{title}</h2>
          <button onClick={onClose} className="p-2 rounded-lg transition flex-shrink-0" onMouseEnter={(e: React.MouseEvent<HTMLButtonElement>) => e.currentTarget.style.backgroundColor = 'var(--bg-secondary)'} onMouseLeave={(e: React.MouseEvent<HTMLButtonElement>) => e.currentTarget.style.backgroundColor = 'transparent'}>
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-3 sm:p-4">
          {children}
        </div>
      </div>

      <style jsx>{`
        @keyframes fade-in {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes slide-in-left {
          from { transform: translateX(-100%); }
          to { transform: translateX(0); }
        }
        @keyframes slide-in-right {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
        .animate-fade-in { animation: fade-in 0.2s ease-out; }
        .animate-slide-in-left { animation: slide-in-left 0.3s ease-out; }
        .animate-slide-in-right { animation: slide-in-right 0.3s ease-out; }
      `}</style>
    </>
  );
}
