import React, { useEffect } from 'react';
import { X } from 'lucide-react';

export default function SlideOutPanel({ 
  isOpen, 
  onClose, 
  direction = 'right',
  width = 'w-96',
  title,
  children 
}) {
  useEffect(() => {
    const handleEsc = (e) => {
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
        className={`fixed top-0 ${direction === 'left' ? 'left-0' : 'right-0'} h-full ${width} bg-gradient-to-br from-gray-900 to-black border-${direction === 'left' ? 'r' : 'l'} border-white/10 z-50 flex flex-col shadow-2xl animate-slide-in-${direction}`}
      >
        <div className="flex-shrink-0 flex items-center justify-between p-4 border-b border-white/10">
          <h2 className="text-lg font-bold">{title}</h2>
          <button onClick={onClose} className="p-2 hover:bg-white/10 rounded-lg transition">
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
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