import React, { useEffect, useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CheckCircle2,
  Loader2,
  Clock,
  AlertTriangle,
  RefreshCw,
  ShieldCheck,
  BarChart2,
  Sparkles,
  Database,
  Search,
  LineChart,
  GitBranch,
  TrendingUp,
  Brain,
  FlaskConical,
  Award,
  FileSpreadsheet,
  Terminal,
  ChevronDown,
  ChevronUp,
  XCircle,
} from 'lucide-react';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import {
  useAnalysisStore,
  type AgentProgress,
  type PipelineStageDef,
} from '../store/useAnalysisStore';
import { API_URL, apiHeaders } from '../lib/api';

interface AgentPipelineTrackerProps {
  jobId: string;
  onComplete?: () => void;
  onCancel?: () => void;
  className?: string;
}

// Canonical fallback definition of all 15 real stages in order
const DEFAULT_PIPELINE_STAGES: PipelineStageDef[] = [
  {
    id: 'profile',
    name: 'Data Profiler',
    phase: 'Ingestion & Quality',
    description: 'Profiles dataset schema, missingness, and column statistics.',
  },
  {
    id: 'data_cleaner',
    name: 'Data Quality & Cleaning Agent',
    phase: 'Ingestion & Quality',
    description: 'Deduplicates, standardizes casing, handles missing values, and records audit trail.',
  },
  {
    id: 'hypothesis_planner',
    name: 'Research Planning Agent',
    phase: 'Hypotheses & EDA',
    description: 'Formulates empirical business hypotheses and identifies key investigation priorities.',
  },
  {
    id: 'data_scientist',
    name: 'Data Scientist Agent',
    phase: 'Hypotheses & EDA',
    description: 'Executes quantitative hypothesis tests, effect sizes, and subgroup comparisons.',
  },
  {
    id: 'reflector',
    name: 'Reflector Agent',
    phase: 'Peer Review & Verification',
    description: 'Evaluates analytical rigor, checks confounders, and triggers deeper investigation loops.',
  },
  {
    id: 'viz_preprocessor',
    name: 'Visualization Preprocessor',
    phase: 'Visual Analytics',
    description: 'Extracts chart specifications and coordinates narrative visualization goals.',
  },
  {
    id: 'viz_coder',
    name: 'Visualization Agent',
    phase: 'Visual Analytics',
    description: 'Generates and executes custom matplotlib/seaborn code in isolated Python sandbox.',
  },
  {
    id: 'causal_analyst',
    name: 'Causal Inference Agent',
    phase: 'Advanced Intelligence',
    description: 'Evaluates potential confounders and differentiates correlation from causation.',
  },
  {
    id: 'forecaster',
    name: 'Forecasting Agent',
    phase: 'Advanced Intelligence',
    description: 'Discovers temporal signals, projects trend horizons, and models trajectories.',
  },
  {
    id: 'anomaly_detector',
    name: 'Anomaly Detection Agent',
    phase: 'Advanced Intelligence',
    description: 'Detects statistical outliers, isolation patterns, and high-risk cohorts.',
  },
  {
    id: 'experimentation',
    name: 'A/B Experimentation Agent',
    phase: 'Advanced Intelligence',
    description: 'Validates Sample Ratio Mismatch (SRM), computes lift % and rollout decision.',
  },
  {
    id: 'ml_modeler',
    name: 'Machine Learning Agent',
    phase: 'Predictive Modeling',
    description: 'Trains predictive ML models (Random Forest) and extracts top driver importances.',
  },
  {
    id: 'strategic_advisor',
    name: 'Strategic Insights Agent',
    phase: 'Executive Synthesis',
    description: 'Translates quantitative findings into high-impact CEO strategic recommendations.',
  },
  {
    id: 'report_writer',
    name: 'Report Writer & Stitcher',
    phase: 'Executive Synthesis',
    description: 'Drafts structured narrative sections and synthesizes comprehensive report body.',
  },
  {
    id: 'auditor',
    name: 'Quality Auditor Agent',
    phase: 'Quality Assurance',
    description: 'Scores analytical rigor, methodology, and triggers self-correction loops if needed.',
  },
];

const STAGE_ICONS: Record<string, React.ReactNode> = {
  profile: <Database className="w-4 h-4" />,
  data_cleaner: <Sparkles className="w-4 h-4" />,
  hypothesis_planner: <Search className="w-4 h-4" />,
  data_scientist: <BarChart2 className="w-4 h-4" />,
  reflector: <RefreshCw className="w-4 h-4" />,
  viz_preprocessor: <LineChart className="w-4 h-4" />,
  viz_coder: <FileSpreadsheet className="w-4 h-4" />,
  causal_analyst: <GitBranch className="w-4 h-4" />,
  forecaster: <TrendingUp className="w-4 h-4" />,
  anomaly_detector: <AlertTriangle className="w-4 h-4" />,
  experimentation: <FlaskConical className="w-4 h-4" />,
  ml_modeler: <Brain className="w-4 h-4" />,
  strategic_advisor: <Award className="w-4 h-4" />,
  report_writer: <FileSpreadsheet className="w-4 h-4" />,
  auditor: <ShieldCheck className="w-4 h-4" />,
  finalize: <CheckCircle2 className="w-4 h-4" />,
};

export const AgentPipelineTracker: React.FC<AgentPipelineTrackerProps> = ({
  jobId,
  onComplete,
  onCancel,
  className = '',
}) => {
  const {
    backendStatus,
    currentAgent,
    agentProgress,
    pipelineStages,
    auditScore,
    dataMeta,
    progress,
    status,
    errorMessage,
    applyJobUpdate,
  } = useAnalysisStore();

  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [showLogDrawer, setShowLogDrawer] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  // Active stages list from backend or canonical fallback
  const stages = useMemo(() => {
    return pipelineStages.length > 0 ? pipelineStages : DEFAULT_PIPELINE_STAGES;
  }, [pipelineStages]);

  // Map of completed or active agents keyed by stage id
  const progressMap = useMemo(() => {
    const map = new Map<string, AgentProgress>();
    for (const ap of agentProgress) {
      map.set(ap.id, ap);
    }
    return map;
  }, [agentProgress]);

  // Elapsed timer
  useEffect(() => {
    if (status === 'complete' || status === 'error') return;
    const interval = setInterval(() => {
      setElapsedSeconds((s) => s + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [status]);

  // Real-Time SSE Stream with fallback 1-second polling
  useEffect(() => {
    let isMounted = true;
    let sseSource: EventSource | null = null;
    let pollInterval: any = null;

    const startPolling = () => {
      pollInterval = setInterval(async () => {
        if (!isMounted) return;
        try {
          const res = await fetch(`${API_URL}/api/jobs/${jobId}/status`, {
            headers: apiHeaders(),
          });
          if (!res.ok) return;
          const data = await res.json();
          if (isMounted && data && !data.error) {
            applyJobUpdate(data);
            if (data.status === 'Complete') {
              if (onComplete) onComplete();
              clearInterval(pollInterval);
            }
          }
        } catch (e) {
          // Keep silent and retry next interval
        }
      }, 1000);
    };

    // Try EventSource SSE first for zero-latency updates
    try {
      if (typeof window !== 'undefined' && window.EventSource) {
        sseSource = new EventSource(`${API_URL}/api/jobs/${jobId}/events`);
        sseSource.onmessage = (event) => {
          if (!isMounted) return;
          try {
            const data = JSON.parse(event.data);
            applyJobUpdate(data);
            if (data.status === 'Complete') {
              if (onComplete) onComplete();
              if (sseSource) sseSource.close();
            }
          } catch (e) {
            // JSON parse error
          }
        };

        sseSource.onerror = () => {
          // If SSE fails or disconnects, fallback to steady 1s polling
          if (sseSource) {
            sseSource.close();
            sseSource = null;
          }
          if (!pollInterval) {
            startPolling();
          }
        };
      } else {
        startPolling();
      }
    } catch {
      startPolling();
    }

    return () => {
      isMounted = false;
      if (sseSource) sseSource.close();
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [jobId, applyJobUpdate, onComplete]);

  // Handle Cancel
  const handleCancel = async () => {
    setCancelling(true);
    try {
      await fetch(`${API_URL}/api/jobs/${jobId}`, {
        method: 'DELETE',
        headers: apiHeaders(),
      });
      if (onCancel) onCancel();
    } catch (e) {
      console.error('Failed to cancel job:', e);
    } finally {
      setCancelling(false);
    }
  };

  // Format elapsed time (MM:SS)
  const formatTime = (secs: number) => {
    const mins = Math.floor(secs / 60);
    const remaining = secs % 60;
    return `${mins}:${remaining < 10 ? '0' : ''}${remaining}`;
  };

  // Group stages by phase
  const stagesByPhase = useMemo(() => {
    const groups: { phase: string; items: PipelineStageDef[] }[] = [];
    for (const st of stages) {
      let grp = groups.find((g) => g.phase === st.phase);
      if (!grp) {
        grp = { phase: st.phase, items: [] };
        groups.push(grp);
      }
      grp.items.push(st);
    }
    return groups;
  }, [stages]);

  const activeAgentName = useMemo(() => {
    if (!currentAgent) return null;
    const found = stages.find((s) => s.id === currentAgent);
    return found ? found.name : currentAgent;
  }, [currentAgent, stages]);

  const completedCount = useMemo(() => {
    return agentProgress.filter((a) => a.status === 'completed').length;
  }, [agentProgress]);

  return (
    <div className={`w-full bg-surface border border-border rounded-[16px] overflow-hidden shadow-sm ${className}`}>
      {/* ── Active Banner & Header ────────────────────────────────────── */}
      <div className="p-5 border-b border-border bg-gradient-to-b from-bg/40 to-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center text-accent">
              {status === 'complete' ? (
                <CheckCircle2 className="w-4 h-4 text-success" />
              ) : status === 'error' ? (
                <AlertTriangle className="w-4 h-4 text-error" />
              ) : (
                <Loader2 className="w-4 h-4 animate-spin" />
              )}
            </div>
            <div>
              <h3 className="font-heading text-[16px] text-fg font-medium tracking-tight">
                {status === 'complete'
                  ? 'Autonomous Analysis Complete'
                  : status === 'error'
                  ? 'Analysis Interrupted'
                  : activeAgentName
                  ? `${activeAgentName} Active`
                  : 'Autonomous Analytics Pipeline Running'}
              </h3>
              <p className="font-body text-[12px] text-fg/60">
                {backendStatus || 'Coordinating multi-agent analytical team...'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {dataMeta && (
              <span className="font-body text-[11px] text-fg/70 bg-bg px-2.5 py-1 rounded-[6px] border border-border">
                {dataMeta.rows.toLocaleString()} rows × {dataMeta.columns} cols
              </span>
            )}
            <span className="font-body text-[11px] text-fg/60 bg-bg px-2.5 py-1 rounded-[6px] border border-border">
              {formatTime(elapsedSeconds)}
            </span>
            {auditScore !== null && (
              <Badge variant={auditScore >= 80 ? 'success' : 'warning'}>
                AUDIT {auditScore}/100
              </Badge>
            )}
            {status !== 'complete' && status !== 'error' && (
              <Badge variant="accent">LIVE PIPELINE</Badge>
            )}
          </div>
        </div>

        {/* Real Progress Bar */}
        <div className="space-y-1.5">
          <div className="flex justify-between items-center text-[11px] font-body text-fg/60">
            <span>
              {completedCount} of {stages.length} autonomous stages completed
            </span>
            <span className="font-medium text-fg">{progress}%</span>
          </div>
          <div className="h-2 w-full bg-bg rounded-full overflow-hidden border border-border/50">
            <motion.div
              className={`h-full rounded-full transition-all duration-300 ${
                status === 'error' ? 'bg-error' : 'bg-accent'
              }`}
              initial={{ width: 0 }}
              animate={{ width: `${Math.max(progress, 3)}%` }}
            />
          </div>
        </div>
      </div>

      {/* ── Error Banner (if any) ─────────────────────────────────────── */}
      {status === 'error' && errorMessage && (
        <div className="p-4 bg-error/10 border-b border-error/20 flex items-start gap-3 text-error">
          <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <h4 className="font-body font-medium text-[13px]">Analysis Encountered an Error</h4>
            <p className="font-body text-[12px] opacity-90 mt-0.5">{errorMessage}</p>
          </div>
        </div>
      )}

      {/* ── Live Stages View ─────────────────────────────────────────── */}
      <div className="divide-y divide-border/60 max-h-[520px] overflow-y-auto">
        {stagesByPhase.map((group) => (
          <div key={group.phase} className="p-4 bg-surface/50">
            <h4 className="font-body text-[10px] font-semibold text-fg/40 uppercase tracking-wider mb-2.5 px-1">
              {group.phase}
            </h4>
            <div className="space-y-2">
              {group.items.map((stage) => {
                const prog = progressMap.get(stage.id);
                const isCompleted = prog?.status === 'completed';
                const isFailed = prog?.status === 'failed';
                const isRunning = !isCompleted && !isFailed && (prog?.status === 'running' || currentAgent === stage.id);
                const hasRound = (prog?.round || 0) > 0;

                return (
                  <motion.div
                    key={stage.id}
                    layout
                    className={`p-3 rounded-[10px] border transition-all ${
                      isRunning
                        ? 'bg-accent/5 border-accent/40 shadow-sm'
                        : isCompleted
                        ? 'bg-bg/40 border-border/80'
                        : 'bg-transparent border-transparent opacity-65'
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      {/* Stage Icon Status */}
                      <div className="mt-0.5 flex-shrink-0">
                        {isRunning ? (
                          <div className="w-5 h-5 rounded-full bg-accent/15 border border-accent flex items-center justify-center text-accent">
                            <Loader2 className="w-3 h-3 animate-spin" />
                          </div>
                        ) : isCompleted ? (
                          <div className="w-5 h-5 rounded-full bg-success/15 border border-success/40 flex items-center justify-center text-success">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                          </div>
                        ) : isFailed ? (
                          <div className="w-5 h-5 rounded-full bg-error/15 border border-error/40 flex items-center justify-center text-error">
                            <XCircle className="w-3.5 h-3.5" />
                          </div>
                        ) : (
                          <div className="w-5 h-5 rounded-full bg-border/40 border border-border flex items-center justify-center text-fg/30">
                            <Clock className="w-3 h-3" />
                          </div>
                        )}
                      </div>

                      {/* Stage Name & Details */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="text-fg/50 flex-shrink-0">
                              {STAGE_ICONS[stage.id] || <BarChart2 className="w-3.5 h-3.5" />}
                            </span>
                            <h5 className={`font-body font-medium text-[13px] ${isRunning ? 'text-accent font-semibold' : 'text-fg'}`}>
                              {stage.name}
                            </h5>
                          </div>

                          <div className="flex items-center gap-1.5 flex-shrink-0">
                            {isRunning && (
                              <Badge variant="accent" className="animate-pulse">
                                RUNNING
                              </Badge>
                            )}
                            {isCompleted && (
                              <span className="font-body text-[10px] text-success font-medium">
                                Completed
                              </span>
                            )}
                            {hasRound && (
                              <Badge variant="warning">
                                Retry {prog?.round}/3
                              </Badge>
                            )}
                            {prog?.score !== undefined && (
                              <Badge variant={prog.score >= 80 ? 'success' : 'warning'}>
                                {prog.score}/100
                              </Badge>
                            )}
                            {!prog && (
                              <span className="font-body text-[10px] text-fg/35">
                                Queued
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Real Detail or Description */}
                        <p className={`font-body text-[11px] mt-1 leading-relaxed ${
                          isRunning ? 'text-fg/80 font-medium' : isCompleted ? 'text-fg/70' : 'text-fg/40'
                        }`}>
                          {prog?.detail || stage.description}
                        </p>
                      </div>
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* ── Toggleable Activity Log Drawer ────────────────────────────── */}
      <AnimatePresence>
        {showLogDrawer && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-t border-border bg-[#111827] text-white p-4 font-mono text-[11px] overflow-hidden"
          >
            <div className="flex items-center justify-between mb-2 pb-2 border-b border-white/10">
              <span className="flex items-center gap-2 text-white/70">
                <Terminal className="w-3.5 h-3.5 text-accent" />
                Live Agent Execution Activity Feed
              </span>
              <span className="text-[10px] text-white/40">{agentProgress.length} events logged</span>
            </div>
            <div className="max-h-48 overflow-y-auto space-y-1.5 pr-1">
              {agentProgress.length === 0 ? (
                <div className="text-white/40 italic">Waiting for initial agent dispatch event...</div>
              ) : (
                agentProgress.map((ap, idx) => (
                  <div key={idx} className="flex items-start gap-2 leading-tight">
                    <span className="text-white/40 text-[10px] flex-shrink-0">
                      [{idx + 1}]
                    </span>
                    <span className={ap.status === 'completed' ? 'text-emerald-400 font-semibold' : 'text-sky-300'}>
                      [{ap.name}]:
                    </span>
                    <span className="text-white/80">{ap.detail}</span>
                  </div>
                ))
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Footer Controls ───────────────────────────────────────────── */}
      <div className="p-3.5 border-t border-border bg-bg/50 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setShowLogDrawer(!showLogDrawer)}
          className="inline-flex items-center gap-1.5 text-[11px] font-body text-fg/60 hover:text-fg transition-colors"
        >
          <Terminal className="w-3.5 h-3.5 text-accent" />
          <span>{showLogDrawer ? 'Hide Activity Log' : 'Show Live Activity Log'}</span>
          {showLogDrawer ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        </button>

        {status !== 'complete' && status !== 'error' && (
          <Button
            variant="outlined"
            size="sm"
            onClick={handleCancel}
            disabled={cancelling}
            className="text-[11px] h-7 px-3 text-error/80 border-error/30 hover:bg-error/10 hover:border-error"
          >
            {cancelling ? (
              <span className="flex items-center gap-1.5">
                <Loader2 className="w-3 h-3 animate-spin" />
                Cancelling...
              </span>
            ) : (
              'Cancel Analysis'
            )}
          </Button>
        )}
      </div>
    </div>
  );
};
