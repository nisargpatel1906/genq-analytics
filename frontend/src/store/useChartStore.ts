import { create } from 'zustand';

// Industry Standard Categorical Palette (Tableau 10)
export const DEFAULT_CHART_COLORS = [
  '#4E79A7', '#F28E2B', '#E15759', '#76B7B2', '#59A14F', 
  '#EDC949', '#AF7AA1', '#FF9DA7', '#9C755F', '#BAB0AB'
];

export interface ChartConfig {
  id: string;
  colors: string[];
  showGridLines: boolean;
  showDataLabels: boolean;
  showLegend: boolean;
  backgroundColor: string;
  axisFontSize: number;
  axisColor: string;
}

interface ChartStore {
  configs: Record<string, ChartConfig>;
  activeChartId: string | null;
  isCustomizerOpen: boolean;
  openCustomizer: (chartId: string) => void;
  closeCustomizer: () => void;
  updateConfig: (chartId: string, updates: Partial<ChartConfig>) => void;
  resetConfig: (chartId: string) => void;
}

const defaultConfig: Omit<ChartConfig, 'id'> = {
  colors: DEFAULT_CHART_COLORS,
  showGridLines: true,
  showDataLabels: false,
  showLegend: true,
  backgroundColor: 'transparent',
  axisFontSize: 11,
  axisColor: '#333333', // Standard dark gray/black for axis
};

export const useChartStore = create<ChartStore>((set) => ({
  configs: {},
  activeChartId: null,
  isCustomizerOpen: false,
  openCustomizer: (chartId) => set((state) => ({
    activeChartId: chartId,
    isCustomizerOpen: true,
    configs: {
      ...state.configs,
      [chartId]: state.configs[chartId] || { id: chartId, ...defaultConfig }
    }
  })),
  closeCustomizer: () => set({ isCustomizerOpen: false, activeChartId: null }),
  updateConfig: (chartId, updates) => set((state) => ({
    configs: {
      ...state.configs,
      [chartId]: { ...state.configs[chartId], ...updates }
    }
  })),
  resetConfig: (chartId) => set((state) => ({
    configs: {
      ...state.configs,
      [chartId]: { id: chartId, ...defaultConfig }
    }
  }))
}));
