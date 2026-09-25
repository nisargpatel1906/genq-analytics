import { create } from 'zustand';
import { API_URL, apiHeaders } from '../lib/api';

export type JobProgressStatus = 'idle' | 'uploading' | 'mapping' | 'analyzing' | 'visualizing' | 'complete' | 'error';

export interface AgentProgress {
  id: string;
  name: string;
  status: 'running' | 'completed' | 'failed' | 'pending';
  detail: string;
  round: number;
  score?: number;
  timestamp?: string;
}

export interface PipelineStageDef {
  id: string;
  name: string;
  phase: string;
  description: string;
}

export interface BackendJobStatus {
  step: number;
  status: string;
  current_agent?: string;
  report_id: string | null;
  rows?: number;
  columns?: number;
  agent_progress?: AgentProgress[];
  pipeline_stages?: PipelineStageDef[];
  audit_score?: number;
  regeneration_round?: number;
  error?: string;
  cancelled?: boolean;
}

export interface ChartItem {
  title: string;
  interpretation: string;
  image: string;
}

export interface ReportSectionFinding {
  title?: string;
  detail?: string;
  confidence?: number;
  impact_score?: number;
  effect_size?: string;
  practical_significance?: string;
  supporting_chart?: string;
}

export interface ReportSection {
  type: 'findings_group' | 'data_overview' | 'trend_analysis' | 'anomalies' | 'comparison' | 'data_table' | 'recommendations' | 'narrative';
  title: string;
  content?: string;
  narrative?: string;
  findings?: ReportSectionFinding[];
  anomalies?: { column?: string; severity?: string; description?: string; businessImpact?: string }[];
  recommendations?: { action?: string; rationale?: string; priority?: string; expected_outcome?: string }[];
  headers?: string[];
  rows?: string[][];
}

export interface ReportData {
  id: string;
  filename: string;
  created_at?: string;
  report: {
    report_planning?: {
      data_relevance_evaluation?: string;
      narrative_flow_strategy?: string;
    };
    domain?: string;
    executiveSummary?: string;
    methodology?: string;
    reportSections?: ReportSection[];
    limitations?: string[];
    keyFindings?: { title?: string; finding?: string; detail?: string; description?: string; confidenceScore?: number; confidence?: number; effect_size?: string; practical_significance?: string; impact_score?: number }[];
    anomalies?: { column?: string; severity?: string; description?: string; businessImpact?: string }[];
    recommendations?: { action?: string; rationale?: string; priority?: string; expected_outcome?: string }[];
    strategic_brief?: any;
    causal_analysis?: any;
    forecast?: any;
    anomaly_detection?: any;
    strategic_recommendations?: any;
    executive_headline?: string;
    data_cleaning_manifest?: any;
    investigation_plan?: any;
    ml_predictive_modeling?: any;
    relational_manifest?: any;
    experiment_results?: any;
    [key: string]: any;
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

  pipelineStages: PipelineStageDef[];
  currentAgent: string | null;

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
  setPipelineStages: (stages: PipelineStageDef[]) => void;
  setCurrentAgent: (agent: string | null) => void;
  setAuditScore: (score: number | null) => void;
  setJobStatus: (status: BackendJobStatus | null) => void;
  setJobError: (error: string | null) => void;
  applyJobUpdate: (jobData: BackendJobStatus) => void;
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
  pipelineStages: [],
  currentAgent: null,
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
  setPipelineStages: (pipelineStages) => set({ pipelineStages }),
  setCurrentAgent: (currentAgent) => set({ currentAgent }),
  setAuditScore: (auditScore) => set({ auditScore }),
  setJobStatus: (jobStatus) => set({ jobStatus }),
  setJobError: (jobError) => set({ jobError }),
  applyJobUpdate: (jobData) => {
    const isComplete = jobData.status === 'Complete' || jobData.step === 3 || jobData.step === 4;
    const isError = jobData.status === 'Failed' || !!jobData.error;
    const isCancelled = jobData.status === 'Cancelled' || !!jobData.cancelled;

    const stages = (jobData.pipeline_stages && jobData.pipeline_stages.length > 0)
      ? jobData.pipeline_stages
      : get().pipelineStages;
    const agentList = jobData.agent_progress || [];
    const completedCount = agentList.filter((a) => a.status === 'completed').length;
    const totalStages = Math.max(stages.length, 14);
    const activeBonus = jobData.current_agent ? 0.5 : 0;
    const computedPct = isComplete
      ? 100
      : Math.min(Math.round(((completedCount + activeBonus) / totalStages) * 100), 98);

    set((state) => ({
      jobStatus: jobData,
      backendStatus: jobData.status || state.backendStatus,
      currentAgent: jobData.current_agent !== undefined ? jobData.current_agent : state.currentAgent,
      agentProgress: agentList.length > 0 ? agentList : state.agentProgress,
      pipelineStages: stages.length > 0 ? stages : state.pipelineStages,
      auditScore: typeof jobData.audit_score === 'number' ? jobData.audit_score : state.auditScore,
      dataMeta: (jobData.rows && jobData.columns)
        ? { rows: jobData.rows, columns: jobData.columns }
        : state.dataMeta,
      progress: computedPct,
      status: isComplete ? 'complete' : isError ? 'error' : isCancelled ? 'error' : 'analyzing',
      errorMessage: isError ? (jobData.error || 'Analysis failed.') : state.errorMessage,
      jobError: isError ? (jobData.error || 'Analysis failed.') : state.jobError,
    }));
  },
  clearJobState: () => set({
    jobId: null,
    status: 'idle',
    progress: 0,
    backendStatus: '',
    errorMessage: '',
    dataMeta: null,
    agentProgress: [],
    pipelineStages: [],
    currentAgent: null,
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
