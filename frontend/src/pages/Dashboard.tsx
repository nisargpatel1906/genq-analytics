import React, { useEffect, useRef, useState } from 'react';
import { Sparkles, Send, MessageSquare, X, Loader2, Bot, User, FileText, AlertTriangle, Target } from 'lucide-react';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { motion, AnimatePresence } from 'framer-motion';
import { useSearchParams } from 'react-router-dom';

// ─── Types ────────────────────────────────────────────────────────────────────
interface ChatMsg { role: 'user' | 'assistant'; content: string; }
interface ChartItem { title: string; interpretation: string; image: string; }

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
  const [messages, setMessages] = useState<ChatMsg[]>([
    {
      role: 'assistant',
      content: `Hi! I've read your dataset report. Ask me anything — I can explain findings, rewrite sections, highlight risks, or suggest next steps.`,
    },
  ]);
  const [input, setInput] = useState('');
  const [thinking, setThinking] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, thinking]);

  const send = async (text: string) => {
    if (!text.trim() || thinking) return;
    const userMsg: ChatMsg = { role: 'user', content: text };
    const history = [...messages];
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setThinking(true);

    try {
      const resp = await fetch(`http://localhost:8000/api/reports/${reportId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history }),
      });
      const data = await resp.json();
      setMessages(prev => [...prev, { role: 'assistant', content: data.reply || 'Sorry, I got an empty response.' }]);
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Connection error. Is the backend running?' }]);
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
            <p className="font-body text-[10px] text-fg/50">Powered by your local Ollama model</p>
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
  const reportId = searchParams.get('report') || '';

  const [reportData, setReportData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [charts, setCharts] = useState<ChartItem[]>([]);
  const [chatOpen, setChatOpen] = useState(false);

  useEffect(() => {
    if (!reportId) return;
    setLoading(true);
    setReportData(null);
    setCharts([]);
    fetch(`http://localhost:8000/api/reports/${reportId}`)
      .then(r => r.json())
      .then(data => {
        setReportData(data);
        return fetch(`http://localhost:8000/api/charts/${reportId}`);
      })
      .then(r => r.json())
      .then(data => {
        setCharts(data.charts || []);
        setLoading(false);
        // Auto-open chat after report loads
        setChatOpen(true);
      })
      .catch(() => setLoading(false));
  }, [reportId]);

  return (
    <div className="flex w-full h-[calc(100vh-56px)] overflow-hidden bg-bg">

      {/* ── MAIN CONTENT ──────────────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col overflow-y-auto relative">
        <div className="flex-1 p-8 pb-24 max-w-5xl mx-auto w-full">

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

          {/* ── Content ─────────────────────────────────────────────────── */}
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
              {reportData?.report?.keyFindings?.length > 0 && (
                <div className="bg-surface border border-border rounded-xl p-6 shadow-sm">
                  <div className="flex items-center gap-2 mb-4">
                    <Sparkles className="w-4 h-4 text-accent" />
                    <span className="font-body text-[10px] text-accent uppercase tracking-widest font-semibold">Key Findings</span>
                  </div>
                  <div className="space-y-4">
                    {reportData.report.keyFindings.map((f: any, i: number) => (
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
              {reportData?.report?.anomalies?.length > 0 && (
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
                        {reportData.report.anomalies.map((a: any, i: number) => (
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
              {reportData?.report?.recommendations?.length > 0 && (
                <div className="bg-surface border border-border rounded-xl p-6 shadow-sm">
                  <div className="flex items-center gap-2 mb-4">
                    <Target className="w-4 h-4 text-accent" />
                    <span className="font-body text-[10px] text-accent uppercase tracking-widest font-semibold">Strategic Recommendations</span>
                  </div>
                  <div className="flex flex-col divide-y divide-border/50">
                    {reportData.report.recommendations.map((rec: any, i: number) => (
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
                <Button variant="outlined" onClick={() => window.location.href = '/library'}>
                  Open Library
                </Button>
                <Button variant="primary" onClick={() => window.location.href = '/upload'}>
                  Upload Dataset
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* Sticky bottom bar */}
        {reportId && (
          <div className="sticky bottom-0 w-full bg-bg/90 backdrop-blur-sm border-t border-border p-4 flex justify-between items-center z-20">
            <div className="flex items-center gap-2 font-body text-[12px] text-fg/50">
              <Sparkles className="w-3.5 h-3.5" />
              <span>Click "Ask AI" to chat about this report and refine it with prompts</span>
            </div>
            <Button
              size="lg"
              className="shadow-custom-md"
              onClick={() => window.open(`http://localhost:8000/api/export/${reportId}/pdf`, '_blank')}
            >
              <span className="mr-2">🗎</span> Generate Full Report
            </Button>
          </div>
        )}
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
  );
}
