import { create } from 'zustand';
import { API_URL, apiHeaders } from '../lib/api';

export type JobProgressStatus = 'idle' | 'uploading' | 'mapping' | 'analyzing' | 'visualizing' | 'complete' | 'error';

export interface AgentProgress {
  id: string;
  name: string;
  status: 'running' | 'completed';
  detail: string;
  round: number;
  score?: number;
}

export interface BackendJobStatus {
  step: number;
  status: string;
  report_id: string | null;
  rows?: number;
  columns?: number;
  agent_progress?: AgentProgress[];
  audit_score?: number;
  regeneration_round?: number;
  error?: string;
}

export interface ChartItem {
  title: string;
  interpretation: string;
  image: string;
}

export interface ReportData {
  id: string;
  filename: string;
  created_at?: string;
  report: {
    domain?: string;
    executiveSummary?: string;
    keyFindings?: { title?: string; finding?: string; detail?: string; description?: string; confidenceScore?: number; confidence?: number }[];
    anomalies?: { column?: string; severity?: string; description?: string; businessImpact?: string }[];
    recommendations?: { action?: string; rationale?: string; priority?: string }[];
    _meta?: {
      agentWorkflow?: {
        approved?: boolean;
        auditSummary?: string;
        regenerationRounds?: number;
        maxRegenerationRounds?: number;
        auditScore?: number;
        stages?: { id: string; name: string; status: string; round: number; score?: number }[];
      };
      chart_images?: { title: string; interpretation: string; image: string }[];
    };
  };
  stats?: {
    shape?: { rows: number; columns: number };
    numeric_summary?: Record<string, { mean: number; std: number; min: number; max: number }>;
    missing_values?: Record<string, number>;
    statistical_anomalies?: { column: string; outlier_count: number; mean: number }[];
  };
}

export interface ChatMsg {
  role: 'user' | 'assistant';
  content: string;
}

interface AnalysisState {
  // Job Tracking
  jobId: string | null;
  status: JobProgressStatus;
  progress: number;
  backendStatus: string;
  errorMessage: string;
  dataMeta: { rows: number; columns: number } | null;
  agentProgress: AgentProgress[];
  auditScore: number | null;
  jobStatus: BackendJobStatus | null;
  jobError: string | null;

  // Report Tracking
  currentReportId: string | null;
  currentReportData: ReportData | null;
  currentReportCharts: ChartItem[];
  isReportLoading: boolean;
  isChartsLoading: boolean;
  reportError: string;

  // Chat tracking (keyed by reportId)
  messagesByReportId: Record<string, ChatMsg[]>;

  // Actions
  setJobId: (id: string | null) => void;
  setStatus: (status: JobProgressStatus) => void;
  setProgress: (progress: number | ((p: number) => number)) => void;
  setBackendStatus: (status: string) => void;
  setErrorMessage: (msg: string) => void;
  setDataMeta: (meta: { rows: number; columns: number } | null) => void;
  setAgentProgress: (progress: AgentProgress[]) => void;
  setAuditScore: (score: number | null) => void;
  setJobStatus: (status: BackendJobStatus | null) => void;
  setJobError: (error: string | null) => void;
  clearJobState: () => void;

  // Report Actions
  loadReport: (id: string, force?: boolean) => Promise<void>;
  updateReportData: (data: ReportData) => void;
  setReportData: (data: ReportData | null) => void;
  setCharts: (charts: ChartItem[]) => void;

  // Chat Actions
  getMessages: (reportId: string) => ChatMsg[];
  addMessage: (reportId: string, message: ChatMsg) => void;
  setMessages: (reportId: string, messages: ChatMsg[]) => void;
  clearMessages: (reportId: string) => void;
}

const DEFAULT_CHAT = (): ChatMsg[] => [
  {
    role: 'assistant',
    content: `Hi! I've read your dataset report. Ask me anything — I can explain findings, rewrite sections, highlight risks, or suggest next steps.`,
  },
];

export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  // Job Initial State
  jobId: null,
  status: 'idle',
  progress: 0,
  backendStatus: '',
  errorMessage: '',
  dataMeta: null,
  agentProgress: [],
  auditScore: null,
  jobStatus: null,
  jobError: null,

  // Report Initial State
  currentReportId: null,
  currentReportData: null,
  currentReportCharts: [],
  isReportLoading: false,
  isChartsLoading: false,
  reportError: '',

  // Chat Initial State
  messagesByReportId: {},

  // Job Actions
  setJobId: (id) => set({ jobId: id }),
  setStatus: (status) => set({ status }),
  setProgress: (progress) => {
    if (typeof progress === 'function') {
      set((state) => ({ progress: progress(state.progress) }));
    } else {
      set({ progress });
    }
  },
  setBackendStatus: (backendStatus) => set({ backendStatus }),
  setErrorMessage: (errorMessage) => set({ errorMessage }),
  setDataMeta: (dataMeta) => set({ dataMeta }),
  setAgentProgress: (agentProgress) => set({ agentProgress }),
  setAuditScore: (auditScore) => set({ auditScore }),
  setJobStatus: (jobStatus) => set({ jobStatus }),
  setJobError: (jobError) => set({ jobError }),
  clearJobState: () => set({
    jobId: null,
    status: 'idle',
    progress: 0,
    backendStatus: '',
    errorMessage: '',
    dataMeta: null,
    agentProgress: [],
    auditScore: null,
    jobStatus: null,
    jobError: null,
  }),

  // Report Actions
  loadReport: async (id, force = false) => {
    const currentId = get().currentReportId;
    if (currentId === id && get().currentReportData && !force) {
      return;
    }

    set({
      currentReportId: id,
      isReportLoading: true,
      reportError: '',
      isChartsLoading: true,
    });

    try {
      const res = await fetch(`${API_URL}/api/reports/${id}`, { headers: apiHeaders() });
      if (!res.ok) throw new Error('Report not found');
      const reportData = await res.json();
      const rawCharts = reportData?.report?._meta?.chart_images || [];
      const storedCharts = rawCharts.map((ch: any) => ({
        ...ch,
        image: ch.image || (ch.image_b64 ? `data:image/png;base64,${ch.image_b64}` : undefined)
      }));
      set({
        currentReportData: reportData,
        isReportLoading: false,
        currentReportCharts: storedCharts,
        isChartsLoading: false,
      });
    } catch (err: any) {
      set({
        reportError: err.message || 'Failed to load report',
        isReportLoading: false,
        isChartsLoading: false,
      });
    }
  },
  updateReportData: (currentReportData) => {
    const rawCharts = currentReportData?.report?._meta?.chart_images || [];
    const mappedCharts = rawCharts.map((ch: any) => ({
      ...ch,
      image: ch.image || (ch.image_b64 ? `data:image/png;base64,${ch.image_b64}` : undefined)
    }));
    set({
      currentReportData,
      currentReportCharts: mappedCharts,
    });
  },
  setReportData: (currentReportData) => set({ currentReportData }),
  setCharts: (currentReportCharts) => set({ currentReportCharts }),

  // Chat Actions
  getMessages: (reportId) => {
    return get().messagesByReportId[reportId] || DEFAULT_CHAT();
  },
  addMessage: (reportId, message) => {
    const currentMessages = get().getMessages(reportId);
    set((state) => ({
      messagesByReportId: {
        ...state.messagesByReportId,
        [reportId]: [...currentMessages, message],
      },
    }));
  },
  setMessages: (reportId, messages) => {
    set((state) => ({
      messagesByReportId: {
        ...state.messagesByReportId,
        [reportId]: messages,
      },
    }));
  },
  clearMessages: (reportId) => {
    set((state) => {
      const newMessages = { ...state.messagesByReportId };
      delete newMessages[reportId];
      return { messagesByReportId: newMessages };
    });
  },
}));
