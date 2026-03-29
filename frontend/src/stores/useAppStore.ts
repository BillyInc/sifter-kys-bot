import { create } from 'zustand';

interface AnalysisResult {
  [key: string]: any;
}

interface AppState {
  // API config
  apiUrl: string;

  // User
  userId: string | null;
  setUserId: (id: string | null) => void;

  // Active panel
  activePanel: string | null;
  setActivePanel: (panel: string | null) => void;

  // Analysis state
  analysisResults: AnalysisResult[];
  setAnalysisResults: (results: AnalysisResult[]) => void;
  addAnalysisResult: (result: AnalysisResult) => void;

  // Theme
  theme: string;
  setTheme: (theme: string) => void;

  // Formatting helpers
  formatNumber: (num: number) => string;
  formatPrice: (price: number) => string;
}

/**
 * Global app store — replaces prop drilling from App.jsx.
 * Shared state that multiple panels need access to.
 */
const useAppStore = create<AppState>((set, _get) => ({
  // API config
  apiUrl: import.meta.env.VITE_API_URL || 'http://localhost:5000',

  // User
  userId: null,
  setUserId: (id: string | null) => set({ userId: id }),

  // Active panel
  activePanel: null,
  setActivePanel: (panel: string | null) => set({ activePanel: panel }),

  // Analysis state
  analysisResults: [],
  setAnalysisResults: (results: AnalysisResult[]) => set({ analysisResults: results }),
  addAnalysisResult: (result: AnalysisResult) => set((state) => ({
    analysisResults: [...state.analysisResults, result],
  })),

  // Theme
  theme: localStorage.getItem('theme') || 'dark',
  setTheme: (theme: string) => {
    localStorage.setItem('theme', theme);
    set({ theme });
  },

  // Formatting helpers (mirrors App.jsx implementations exactly)
  formatNumber: (num: number): string => {
    if (!num) return '0';
    if (num >= 1e9) return `$${(num / 1e9).toFixed(2)}B`;
    if (num >= 1e6) return `$${(num / 1e6).toFixed(2)}M`;
    if (num >= 1e3) return `$${(num / 1e3).toFixed(2)}K`;
    return `$${num.toFixed(2)}`;
  },

  formatPrice: (price: number): string => {
    if (!price) return '$0';
    if (price < 0.000001) return `$${price.toExponential(2)}`;
    if (price < 0.01)     return `$${price.toFixed(6)}`;
    if (price < 1)        return `$${price.toFixed(4)}`;
    return `$${price.toFixed(2)}`;
  },
}));

export default useAppStore;
