import { useEffect, useRef, useState } from 'react';
import { Sparkles, Send, MessageSquare, X, Loader2, Bot, User, FileText, AlertTriangle, Target, ShieldCheck, CheckCircle2, RefreshCw, Clock } from 'lucide-react';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { motion, AnimatePresence } from 'framer-motion';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { API_URL, apiHeaders } from '../lib/api';
import { useAnalysisStore } from '../store/useAnalysisStore';
import type { ChatMsg } from '../store/useAnalysisStore';

// ─── Quick-prompt suggestions ─────────────────────────────────────────────────
const SUGGESTIONS = [
  'Summarise the key risks in 3 bullet points',
  'What are the top 3 actionable insights?',
  'Rewrite the executive summary in simpler language',
  'Which columns have the most anomalies?',
  'What should I investigate further?',
];

// ─── Chat Panel ───────────────────────────────────────────────────────────────
function ChatPanel({ reportId, onClose }: { reportId: string; onClose: () => void }) {
  const [providerLabel, setProviderLabel] = useState('Configured AI provider');
  const { getMessages, addMessage, setMessages } = useAnalysisStore();
  const messages = getMessages(reportId);
  const [input, setInput] = useState('');
  const [thinking, setThinking] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, thinking]);

  useEffect(() => {
    fetch(`${API_URL}/api/llm/status`, { headers: apiHeaders() })
      .then(r => r.json())
      .then(data => {
        if (data.mode !== 'single') {
          setProviderLabel(`agent workflow; chat ${data.chat || 'configured'}`);
        } else {
          setProviderLabel(data.chat || 'Configured AI provider');
        }
      })
      .catch(() => setProviderLabel('Configured AI provider'));
  }, []);

  const send = async (text: string) => {
    if (!text.trim() || thinking) return;
    const userMsg: ChatMsg = { role: 'user', content: text };
    const history = [...messages];
    addMessage(reportId, userMsg);
    setInput('');
    setThinking(true);

    try {
      const resp = await fetch(`${API_URL}/api/reports/${reportId}/chat`, {
        method: 'POST',
        headers: apiHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ message: text, history }),
      });

      if (!resp.ok) throw new Error('Server error');

      const reader = resp.body?.getReader();
      if (!reader) throw new Error('No stream');

      const decoder = new TextDecoder();
      let assistantContent = '';
      let buffer = '';

      setMessages(reportId, [...history, userMsg, { role: 'assistant' as const, content: '' }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') break;
            if (data.startsWith('[ERROR]')) {
              assistantContent += data.replace('[ERROR] ', '');
            } else {
              assistantContent += data;
            }
            const updated = [...history, userMsg, { role: 'assistant' as const, content: assistantContent }];
            setMessages(reportId, updated);
          }
        }
      }
    } catch {
      setMessages(reportId, [...history, userMsg, { role: 'assistant' as const, content: 'Connection error. Is the backend running?' }]);
    } finally {
      setThinking(false);
    }
  };

  return (
    <motion.div
      initial={{ x: '100%', opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: '100%', opacity: 0 }}
      transition={{ type: 'spring', damping: 28, stiffness: 220 }}
      className="flex flex-col h-full bg-surface border-l border-border"
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full bg-accent flex items-center justify-center">
            <Sparkles className="w-3.5 h-3.5 text-white" />
          </div>
          <div>
            <p className="font-body font-semibold text-[13px] text-fg">Report Assistant</p>
            <p className="font-body text-[10px] text-fg/50">Powered by {providerLabel}</p>
          </div>
        </div>
        <button onClick={onClose} className="text-fg/40 hover:text-fg transition-colors p-1">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((m, i) => (
          <div key={i} className={`flex gap-2.5 ${m.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
            <div className={`w-7 h-7 rounded-full flex-shrink-0 flex items-center justify-center ${
              m.role === 'user' ? 'bg-fg text-bg' : 'bg-accent/15 text-accent'
            }`}>
              {m.role === 'user' ? <User className="w-3.5 h-3.5" /> : <Bot className="w-3.5 h-3.5" />}
            </div>
            <div className={`max-w-[85%] rounded-xl px-3 py-2.5 ${
              m.role === 'user'
                ? 'bg-fg text-bg font-body text-[13px]'
                : 'bg-bg border border-border text-fg font-body text-[13px] leading-relaxed'
            }`}>
              {m.content}
            </div>
          </div>
        ))}

        {thinking && (
          <div className="flex gap-2.5">
            <div className="w-7 h-7 rounded-full bg-accent/15 flex items-center justify-center">
              <Bot className="w-3.5 h-3.5 text-accent" />
            </div>
            <div className="bg-bg border border-border rounded-xl px-4 py-3 flex items-center gap-2">
              <Loader2 className="w-3.5 h-3.5 animate-spin text-accent" />
              <span className="font-body text-[12px] text-fg/60">Thinking…</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions (only shown when chat is empty-ish) */}
      {messages.length <= 1 && (
        <div className="px-4 pb-3 flex flex-wrap gap-1.5">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              className="text-[11px] font-body text-accent border border-accent/30 bg-accent/5 hover:bg-accent/15 rounded-full px-3 py-1 transition-colors text-left"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="p-3 border-t border-border flex-shrink-0">
        <div className="flex items-end gap-2 bg-bg border border-border rounded-xl overflow-hidden focus-within:border-accent transition-colors">
          <textarea
            className="flex-1 font-body text-[13px] text-fg bg-transparent outline-none resize-none px-3 py-2.5 max-h-[120px]"
            placeholder="Ask about the data, or request changes…"
            rows={1}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input); }}}
          />
          <button
            onClick={() => send(input)}
            disabled={thinking || !input.trim()}
            className="m-1.5 w-8 h-8 rounded-lg bg-accent flex items-center justify-center text-white hover:opacity-90 transition-opacity disabled:opacity-30"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
        <p className="font-body text-[10px] text-fg/40 mt-1.5 px-1">Enter to send · Shift+Enter for new line</p>
      </div>
    </motion.div>
  );
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────
export function Dashboard() {
  const [searchParams] = useSearchParams();
  const jobId = searchParams.get('job') || '';
  const [reportId, setReportId] = useState(searchParams.get('report') || '');
  const navigate = useNavigate();

  const [chatOpen, setChatOpen] = useState(false);

  const {
    currentReportData: reportData,
    currentReportCharts: charts,
    isReportLoading: loading,
    loadReport,
    jobStatus,
    setJobStatus,
    agentProgress,
    setAgentProgress,
    auditScore,
    setAuditScore,
    jobError,
    setJobError,
  } = useAnalysisStore();

  const workflow = reportData?.report?._meta?.agentWorkflow;

  // Poll job status when coming from Upload
  useEffect(() => {
    if (!jobId) return;

    let active = true;
    let delay = 3000;

    const poll = async () => {
      if (!active) return;
      try {
        const res = await fetch(`${API_URL}/api/jobs/${jobId}/status`, { headers: apiHeaders() });
        const data = await res.json();

        if (!active) return;

        if (data.error || data.status === 'Failed') {
          setJobError(data.error || 'Analysis failed.');
          return;
        }

        setJobStatus(data);
        if (Array.isArray(data.agent_progress)) setAgentProgress(data.agent_progress);
        if (typeof data.audit_score === 'number') setAuditScore(data.audit_score);

        if (data.step === 4 && data.status === 'Complete') {
          setReportId(data.report_id);
          setJobStatus(null);
          loadReport(data.report_id).then(() => {
            setChatOpen(true);
          });
          return;
        }

        delay = Math.min(delay * 1.5, 15000);
        setTimeout(poll, delay);
      } catch {
        if (active) {
          setJobError('Connection lost.');
        }
      }
    };

    const timerId = setTimeout(poll, delay);

    return () => {
      active = false;
      clearTimeout(timerId);
    };
  }, [jobId, loadReport, setAgentProgress, setAuditScore, setJobError, setJobStatus]);

  useEffect(() => {
    if (reportId && !jobId) {
      loadReport(reportId).then(() => {
        setChatOpen(true);
      });
    }
  }, [reportId, jobId, loadReport]);

  return (
    <div className="flex flex-col w-full h-[calc(100vh-56px)] overflow-hidden bg-bg">

      {/* ── MAIN CONTENT ──────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">
        <main className="flex-1 flex flex-col overflow-y-auto relative">
          <div className="flex-1 p-8 pb-8 max-w-5xl mx-auto w-full">

          {/* Page Header */}
          <div className="flex justify-between items-start mb-8">
            <div>
              {reportData?.report?.domain && (
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant="accent">Domain Detected</Badge>
                  <span className="font-body text-[13px] text-fg/80">{reportData.report.domain}</span>
                </div>
              )}
              <h1 className="font-heading text-[32px] font-bold text-fg leading-tight">
                {reportData ? `Analysis: ${reportData.filename}` : 'Dashboard'}
              </h1>
              <p className="font-body text-[14px] text-fg/60 mt-1">
                {reportData
                  ? `${reportData.stats?.shape?.rows?.toLocaleString() ?? '—'} rows · ${reportData.stats?.shape?.columns ?? '—'} columns`
                  : 'Upload a dataset to get started'}
              </p>
            </div>

            {/* Chat toggle button */}
            {reportId && (
              <button
                onClick={() => setChatOpen(o => !o)}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-xl font-body text-[13px] font-medium border transition-all ${
                  chatOpen
                    ? 'bg-accent text-white border-accent shadow-sm'
                    : 'bg-surface border-border text-fg hover:border-accent'
                }`}
              >
                <MessageSquare className="w-4 h-4" />
                {chatOpen ? 'Close Chat' : 'Ask AI'}
              </button>
            )}
          </div>

          {/* ── Live Progress Panel (when job is running) ──────────────────── */}
          {jobStatus && !reportData && (
            <section className="mb-8 bg-surface border border-border rounded-2xl overflow-hidden shadow-sm">
              {/* Header */}
              <div className="p-5 border-b border-border flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {jobStatus.status === 'Complete' ? (
                    <CheckCircle2 className="w-5 h-5 text-success" />
                  ) : jobStatus.error ? (
                    <AlertTriangle className="w-5 h-5 text-error" />
                  ) : (
                    <Loader2 className="w-5 h-5 text-accent animate-spin" />
                  )}
                  <div>
                    <h2 className="font-body font-semibold text-[15px] text-fg">
                      {jobStatus.status || 'Analyzing...'}
                    </h2>
                    {jobStatus.rows && jobStatus.columns && (
                      <p className="font-body text-[12px] text-fg/50 mt-0.5">
                        {jobStatus.rows.toLocaleString()} rows · {jobStatus.columns} columns
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {auditScore !== null && (
                    <Badge variant={auditScore >= 85 ? 'success' : 'warning'}>
                      Audit {auditScore}/100
                    </Badge>
                  )}
                  {jobStatus.regeneration_round !== undefined && jobStatus.regeneration_round > 0 && (
                    <span className="font-body text-[11px] text-fg/50 flex items-center gap-1.5">
                      <RefreshCw className="w-3.5 h-3.5" />
                      Retry {jobStatus.regeneration_round}/3
                    </span>
                  )}
                </div>
              </div>

              {/* Agent Progress List */}
              {agentProgress.length > 0 && (
                <div className="px-5 py-3 border-b border-border bg-bg/30">
                  {agentProgress.map((agent) => (
                    <div key={agent.id} className="py-3 border-b border-border/50 last:border-0 flex gap-3">
                      <div className="mt-0.5 flex-shrink-0">
                        {agent.status === 'running' ? (
                          agent.round > 0 ? <RefreshCw className="w-4 h-4 text-warning animate-spin" /> : <Loader2 className="w-4 h-4 text-accent animate-spin" />
                        ) : agent.id === 'audit' ? (
                          <ShieldCheck className="w-4 h-4 text-success" />
                        ) : (
                          <CheckCircle2 className="w-4 h-4 text-success" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-3">
                          <h4 className="font-body font-medium text-[13px] text-fg">{agent.name}</h4>
                          <span className="font-body text-[10px] text-fg/50 flex-shrink-0">
                            {agent.score !== undefined ? `${agent.score}/100` : agent.round > 0 ? `Retry ${agent.round}/3` : agent.status}
                          </span>
                        </div>
                        <p className="font-body text-[11px] text-fg/60 mt-1 leading-relaxed">{agent.detail}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Error state */}
              {jobError && (
                <div className="p-5 bg-error/5 border-t border-error/20">
                  <div className="flex items-center gap-2 text-error">
                    <AlertTriangle className="w-4 h-4" />
                    <p className="font-body text-[13px]">{jobError}</p>
                  </div>
                </div>
              )}

              {/* Step indicators */}
              <div className="px-5 py-4">
                {[
                  { step: 1, label: 'Mapping Schema', desc: 'Ingesting data and analyzing structures...' },
                  { step: 2, label: 'Detecting Patterns', desc: 'Running agent workflow...' },
                  { step: 3, label: 'Preparing Visuals', desc: 'Building charts and insights...' },
                  { step: 4, label: 'Complete', desc: 'Report ready' },
                ].map(({ step, label, desc }) => (
                  <div key={step} className="py-3 border-b border-border/50 last:border-0 flex gap-4">
                    <div className="mt-0.5">
                      {(jobStatus?.step || 0) < step ? (
                        <Clock className="w-4 h-4 text-fg/20" />
                      ) : (jobStatus?.step || 0) === step && !jobStatus?.error ? (
                        <Loader2 className="w-4 h-4 text-accent animate-spin" />
                      ) : (
                        <CheckCircle2 className="w-4 h-4 text-success" />
                      )}
                    </div>
                    <div className="flex-1">
                      <h4 className={`font-body font-medium text-[13px] ${(jobStatus?.step || 0) < step ? 'text-fg/40' : 'text-fg'}`}>
                        {label}
                      </h4>
                      <p className={`font-body text-[11px] ${(jobStatus?.step || 0) < step ? 'text-fg/25' : 'text-fg/55'}`}>
                        {(jobStatus?.step || 0) >= step ? desc : 'Waiting...'}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ── Content ─────────────────────────────────────────────────── */}
          {workflow && (
            <section className="mb-8 py-5 border-y border-border">
              <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                <div className="flex items-center gap-3">
                  <ShieldCheck className={`w-5 h-5 ${workflow.approved ? 'text-success' : 'text-warning'}`} />
                  <div>
                    <h2 className="font-body font-semibold text-[14px] text-fg">Agent Quality Audit</h2>
                    <p className="font-body text-[11px] text-fg/55 mt-0.5">{workflow.auditSummary}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {(workflow.regenerationRounds ?? 0) > 0 && (
                    <span className="font-body text-[11px] text-fg/55 flex items-center gap-1.5">
                      <RefreshCw className="w-3.5 h-3.5" />
                      {workflow.regenerationRounds} of {workflow.maxRegenerationRounds} retries
                    </span>
                  )}
                  <Badge variant={workflow.approved ? 'success' : 'warning'}>
                    {workflow.auditScore}/100
                  </Badge>
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-x-5 gap-y-3">
                {workflow.stages?.map((stage: any) => (
                  <div key={stage.id} className="flex items-start gap-2 min-w-0">
                    <CheckCircle2 className="w-3.5 h-3.5 text-success mt-0.5 flex-shrink-0" />
                    <div className="min-w-0">
                      <p className="font-body text-[11px] font-medium text-fg truncate">{stage.name}</p>
                      <p className="font-body text-[10px] text-fg/45 mt-0.5">
                        {stage.id === 'audit' && stage.score !== undefined ? `Score ${stage.score}` : stage.round > 0 ? `Corrected in round ${stage.round}` : 'Completed'}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {loading ? (
            <div className="flex flex-col items-center justify-center py-20 gap-4">
              <Loader2 className="w-8 h-8 animate-spin text-accent" />
              <p className="font-body text-[14px] text-fg/60">Loading charts and insights…</p>
            </div>

          ) : reportData ? (
            <div className="space-y-6">

              {/* Charts */}
              {charts.length > 0 ? (
                charts.map((ch, i) => (
                  <div key={i} className="bg-surface border border-border rounded-xl p-6 shadow-sm">
                    <h3 className="font-heading text-[18px] font-medium mb-4 text-fg">{ch.title}</h3>
                    <img
                      src={ch.image}
                      alt={ch.title}
                      className="w-full rounded-lg"
                      style={{ maxHeight: 420, objectFit: 'contain' }}
                    />
                    <div className="mt-4 p-4 bg-accent/5 border-l-4 border-accent rounded-r-lg">
                      <p className="font-body text-[13px] text-fg/80 leading-relaxed">
                        <span className="font-semibold text-accent">Insight: </span>{ch.interpretation}
                      </p>
                    </div>
                  </div>
                ))
              ) : (
                <div className="flex items-center gap-3 py-12 text-fg/40 bg-surface border border-border rounded-xl px-6">
                  <Sparkles className="w-6 h-6" />
                  <span className="font-body text-[13px]">No charts could be generated for this dataset.</span>
                </div>
              )}

              {/* Executive Summary */}
              {reportData?.report?.executiveSummary && (
                <div className="bg-surface border border-border rounded-xl p-6 shadow-sm">
                  <div className="flex items-center gap-2 mb-3">
                    <FileText className="w-4 h-4 text-accent" />
                    <span className="font-body text-[10px] text-accent uppercase tracking-widest font-semibold">Executive Summary</span>
                  </div>
                  <p className="font-body text-[14px] text-fg/80 leading-[1.8]">{reportData.report.executiveSummary}</p>
                </div>
              )}

              {/* Key Findings */}
              {((reportData?.report?.keyFindings?.length) ?? 0) > 0 && (
                <div className="bg-surface border border-border rounded-xl p-6 shadow-sm">
                  <div className="flex items-center gap-2 mb-4">
                    <Sparkles className="w-4 h-4 text-accent" />
                    <span className="font-body text-[10px] text-accent uppercase tracking-widest font-semibold">Key Findings</span>
                  </div>
                  <div className="space-y-4">
                    {(reportData?.report?.keyFindings || []).map((f: any, i: number) => (
                      <div key={i} className="flex gap-4 items-start p-4 bg-bg rounded-lg border border-border/50">
                        <div className="flex-shrink-0 w-7 h-7 rounded-full bg-accent/10 flex items-center justify-center">
                          <span className="font-body text-[11px] font-bold text-accent">{i + 1}</span>
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between gap-2 mb-1">
                            <h4 className="font-body font-semibold text-[13px] text-fg">{f.title}</h4>
                            {f.confidence && (
                              <span className="font-body text-[11px] text-accent flex-shrink-0">{f.confidence}%</span>
                            )}
                          </div>
                          <p className="font-body text-[13px] text-fg/70 leading-relaxed">{f.detail || f.description || f.finding}</p>
                          {f.confidence && (
                            <div className="mt-2 h-1 bg-border/50 rounded-full">
                              <div className="h-full bg-accent rounded-full" style={{ width: `${f.confidence}%` }} />
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Anomalies */}
              {((reportData?.report?.anomalies?.length) ?? 0) > 0 && (
                <div className="bg-surface border border-border rounded-xl p-6 shadow-sm">
                  <div className="flex items-center gap-2 mb-4">
                    <AlertTriangle className="w-4 h-4 text-amber-500" />
                    <span className="font-body text-[10px] text-amber-600 uppercase tracking-widest font-semibold">Anomalies Detected</span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full font-body text-[13px]">
                      <thead>
                        <tr className="border-b border-border text-fg/50 text-[11px] uppercase tracking-wider">
                          <th className="text-left pb-2 font-medium">Column</th>
                          <th className="text-left pb-2 font-medium">Severity</th>
                          <th className="text-left pb-2 font-medium">Description</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(reportData?.report?.anomalies || []).map((a: any, i: number) => (
                          <tr key={i} className="border-b border-border/40 last:border-0">
                            <td className="py-3 pr-4 font-medium text-fg">{a.column}</td>
                            <td className="py-3 pr-4">
                              <span className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold ${
                                a.severity?.toLowerCase() === 'high' ? 'bg-red-100 text-red-700' :
                                a.severity?.toLowerCase() === 'medium' ? 'bg-amber-100 text-amber-700' :
                                'bg-green-100 text-green-700'
                              }`}>{a.severity}</span>
                            </td>
                            <td className="py-3 text-fg/70 leading-relaxed">{a.description}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Recommendations */}
              {((reportData?.report?.recommendations?.length) ?? 0) > 0 && (
                <div className="bg-surface border border-border rounded-xl p-6 shadow-sm">
                  <div className="flex items-center gap-2 mb-4">
                    <Target className="w-4 h-4 text-accent" />
                    <span className="font-body text-[10px] text-accent uppercase tracking-widest font-semibold">Strategic Recommendations</span>
                  </div>
                  <div className="flex flex-col divide-y divide-border/50">
                    {(reportData?.report?.recommendations || []).map((rec: any, i: number) => (
                      <div key={i} className="flex gap-4 py-4 items-start">
                        <div className="w-7 h-7 rounded-full bg-accent/10 flex items-center justify-center flex-shrink-0">
                          <span className="font-body text-[11px] font-bold text-accent">{i + 1}</span>
                        </div>
                        <div className="flex-1">
                          <h4 className="font-body font-semibold text-[14px] text-fg mb-1">{rec.action}</h4>
                          <p className="font-body text-[13px] text-fg/70">{rec.rationale}</p>
                        </div>
                        <Badge variant={
                          rec.priority?.toLowerCase() === 'high' ? 'error' :
                          rec.priority?.toLowerCase() === 'medium' ? 'warning' : 'success'
                        }>
                          {rec.priority}
                        </Badge>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

          ) : (
            // Empty state
            <div className="flex flex-col items-center justify-center py-28 gap-5 text-center">
              <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center">
                <Sparkles className="w-8 h-8 text-accent/60" />
              </div>
              <h2 className="font-heading text-[26px] text-fg/50">No dataset selected</h2>
              <p className="font-body text-[14px] text-fg/40 max-w-sm">
                Open the <strong>Library</strong> and click "Open on Dashboard" to view charts and insights — or upload a new dataset.
              </p>
              <div className="flex gap-3">
                <Button variant="outlined" onClick={() => navigate('/library')}>
                  Open Library
                </Button>
                <Button variant="primary" onClick={() => navigate('/upload')}>
                  Upload Dataset
                </Button>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* ── AI CHAT PANEL ─────────────────────────────────────────────────── */}
      <AnimatePresence>
        {chatOpen && reportId && (
          <motion.aside
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 380, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ type: 'spring', damping: 28, stiffness: 220 }}
            className="flex-shrink-0 overflow-hidden"
            style={{ minWidth: 0 }}
          >
            <ChatPanel reportId={reportId} onClose={() => setChatOpen(false)} />
          </motion.aside>
        )}
      </AnimatePresence>
      </div>

      {/* ── Sticky bottom export bar ─────────────────────────────────────────── */}
      {reportId && (
        <div className="flex-shrink-0 w-full bg-surface border-t border-border px-6 py-3 flex justify-between items-center z-30">
          <div className="flex items-center gap-2 font-body text-[12px] text-fg/50">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Click "Ask AI" to chat about this report and refine it with prompts</span>
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant="outlined"
              size="sm"
              onClick={() => window.open(`${API_URL}/api/export/${reportId}`, '_blank')}
            >
              Download PDF
            </Button>
            <Button
              size="sm"
              className="shadow-custom-md"
              onClick={() => window.open(`${API_URL}/api/export/${reportId}/pdf`, '_blank')}
            >
              Generate Full Report
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
