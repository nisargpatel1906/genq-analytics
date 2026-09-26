import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeftRight, TrendingUp, TrendingDown, Minus, ChevronRight, BarChart2, Star, Loader2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { API_URL, apiHeaders } from '../lib/api';
import { Button } from '../components/ui/Button';

interface DeltaFinding {
  title: string;
  impact_delta: number;
  confidence_delta: number;
  finding_a: string;
  finding_b: string;
}

interface CompareResult {
  report_a_id: string;
  report_b_id: string;
  report_a_title: string;
  report_b_title: string;
  audit_score_a: number;
  audit_score_b: number;
  audit_score_delta: number;
  shared_findings_count: number;
  only_in_a_count: number;
  only_in_b_count: number;
  delta_findings: DeltaFinding[];
  new_findings_in_b: any[];
  dropped_findings_from_a: any[];
}

interface ReportSummary {
  id: string;
  filename: string;
  created_at: string;
}

const DeltaBadge = ({ delta }: { delta: number }) => {
  if (delta > 0)
    return (
      <span className="flex items-center gap-1 text-success text-[11px] font-bold font-mono">
        <TrendingUp size={11} /> +{delta}
      </span>
    );
  if (delta < 0)
    return (
      <span className="flex items-center gap-1 text-error text-[11px] font-bold font-mono">
        <TrendingDown size={11} /> {delta}
      </span>
    );
  return (
    <span className="flex items-center gap-1 text-muted text-[11px] font-mono">
      <Minus size={11} /> 0
    </span>
  );
};

const ScoreGauge = ({ score, label }: { score: number; label: string }) => {
  const color = score >= 88 ? '#5C6E3E' : score >= 70 ? '#B8860B' : '#8B3A3A';
  return (
    <div className="text-center">
      <div className="relative w-20 h-20 mx-auto mb-2">
        <svg viewBox="0 0 80 80" className="w-full h-full -rotate-90">
          <circle cx="40" cy="40" r="34" fill="none" stroke="#D4C9B0" strokeWidth="6" />
          <circle
            cx="40"
            cy="40"
            r="34"
            fill="none"
            stroke={color}
            strokeWidth="6"
            strokeDasharray={`${(score / 100) * 213.6} 213.6`}
            strokeLinecap="round"
            style={{ transition: 'stroke-dasharray 1s ease' }}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center rotate-0">
          <span className="text-xl font-bold font-mono" style={{ color }}>{score}</span>
        </div>
      </div>
      <p className="text-xs text-muted font-medium font-body">{label}</p>
    </div>
  );
};

export function Compare() {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [reportIdA, setReportIdA] = useState('');
  const [reportIdB, setReportIdB] = useState('');
  const [result, setResult] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [reportsLoading, setReportsLoading] = useState(true);

  // Load available reports
  useEffect(() => {
    fetch(`${API_URL}/api/reports`, { headers: apiHeaders() })
      .then(r => r.json())
      .then(data => { setReports(data.reports || []); setReportsLoading(false); })
      .catch(() => setReportsLoading(false));
  }, []);

  const handleCompare = async () => {
    if (!reportIdA || !reportIdB) return;
    if (reportIdA === reportIdB) { setError('Please select two distinct reports to evaluate delta.'); return; }
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/compare`, {
        method: 'POST',
        headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ report_id_a: reportIdA, report_id_b: reportIdB }),
      });
      if (!res.ok) throw new Error(await res.text());
      setResult(await res.json());
    } catch (e: any) {
      setError(e.message || 'Comparison failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-bg text-fg font-body">
      {/* Header */}
      <div className="border-b border-border bg-surface/90 backdrop-blur-md sticky top-0 z-20 shadow-custom-sm">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center gap-3">
          <div className="w-8 h-8 rounded-[8px] bg-surface-secondary border border-border flex items-center justify-center text-accent">
            <ArrowLeftRight size={18} />
          </div>
          <div>
            <h1 className="font-heading text-2xl font-bold text-fg">Comparative Analytical Delta</h1>
            <p className="text-xs text-muted mt-0.5">Evaluate hypothesis convergence, score migration, and anomaly drift between syntheses</p>
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
        {/* Selection Panel */}
        <div className="bg-surface border border-border rounded-[12px] p-6 shadow-custom-sm">
          <h2 className="font-heading text-[16px] font-semibold text-fg mb-4">Select Syntheses for Cross-Comparison</h2>
          <div className="grid md:grid-cols-2 gap-4">
            {[
              { label: 'Baseline Synthesis (Report A)', value: reportIdA, set: setReportIdA },
              { label: 'Evaluation Synthesis (Report B)', value: reportIdB, set: setReportIdB },
            ].map(({ label, value, set }) => (
              <div key={label}>
                <label className="block text-xs font-semibold text-muted uppercase tracking-[0.06em] mb-1.5">{label}</label>
                {reportsLoading ? (
                  <div className="h-10 bg-surface-secondary/50 rounded-[8px] animate-pulse border border-border" />
                ) : (
                  <select
                    value={value}
                    onChange={e => set(e.target.value)}
                    className="w-full bg-surface border border-border rounded-[8px] px-3.5 py-2.5 text-sm text-fg focus:outline-none focus:border-accent transition-all shadow-custom-sm"
                  >
                    <option value="">— Select an archival synthesis —</option>
                    {reports.map(r => (
                      <option key={r.id} value={r.id}>
                        {r.filename} ({new Date(r.created_at).toLocaleDateString()})
                      </option>
                    ))}
                  </select>
                )}
              </div>
            ))}
          </div>

          {error && <p className="mt-3 text-sm text-error font-medium">{error}</p>}

          <div className="mt-5">
            <Button
              onClick={handleCompare}
              disabled={!reportIdA || !reportIdB || loading}
              className="w-full py-2.5 gap-2"
              variant="primary"
            >
              {loading ? (
                <>
                  <Loader2 size={15} className="animate-spin" /> Synthesizing Comparative Delta…
                </>
              ) : (
                <>
                  <ArrowLeftRight size={15} /> Execute Comparative Delta Analysis
                </>
              )}
            </Button>
          </div>
        </div>

        {/* Results */}
        {result && (
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
            {/* Overview Header */}
            <div className="bg-surface border border-border rounded-[12px] p-6 shadow-custom-sm">
              <div className="grid md:grid-cols-3 gap-6 items-center">
                {/* Report A */}
                <div className="text-center">
                  <div className="inline-block px-3 py-1 rounded-[4px] bg-surface-secondary border border-border text-accent text-[10px] font-bold uppercase tracking-[0.08em] mb-2 font-mono">
                    Baseline (A)
                  </div>
                  <p className="font-heading text-sm font-semibold text-fg">{result.report_a_title}</p>
                  <Link to={`/reports/${result.report_a_id}`} className="text-xs text-accent hover:underline mt-1 inline-block">
                    View Archival Synthesis &rarr;
                  </Link>
                </div>

                {/* Score comparison */}
                <div className="flex items-center justify-center gap-4">
                  <ScoreGauge score={result.audit_score_a} label="Audit Score A" />
                  <div className="text-center">
                    <DeltaBadge delta={result.audit_score_delta} />
                    <p className="text-[10px] text-muted mt-1 font-body">Score Delta</p>
                  </div>
                  <ScoreGauge score={result.audit_score_b} label="Audit Score B" />
                </div>

                {/* Report B */}
                <div className="text-center">
                  <div className="inline-block px-3 py-1 rounded-[4px] bg-surface-secondary border border-accent/40 text-accent text-[10px] font-bold uppercase tracking-[0.08em] mb-2 font-mono">
                    Evaluation (B)
                  </div>
                  <p className="font-heading text-sm font-semibold text-fg">{result.report_b_title}</p>
                  <Link to={`/reports/${result.report_b_id}`} className="text-xs text-accent hover:underline mt-1 inline-block">
                    View Archival Synthesis &rarr;
                  </Link>
                </div>
              </div>

              {/* Stats row */}
              <div className="grid grid-cols-3 gap-4 mt-6 pt-5 border-t border-border">
                {[
                  { label: 'Corroborated Findings', value: result.shared_findings_count, color: 'text-fg' },
                  { label: 'Unique to Baseline (A)', value: result.only_in_a_count, color: 'text-accent' },
                  { label: 'Newly Identified in (B)', value: result.only_in_b_count, color: 'text-success' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="text-center">
                    <p className={`text-2xl font-bold font-mono ${color}`}>{value}</p>
                    <p className="text-[11px] text-muted mt-0.5 font-body">{label}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Delta Findings */}
            {result.delta_findings.length > 0 && (
              <div className="bg-surface border border-border rounded-[12px] p-6 shadow-custom-sm">
                <h2 className="font-heading text-base font-bold text-fg mb-4 flex items-center gap-2">
                  <BarChart2 size={16} className="text-accent" />
                  Corroborated Findings — Variance Analysis
                  <span className="text-muted font-normal text-xs ml-1 font-body">(Ranked by magnitude of shift)</span>
                </h2>
                <div className="space-y-3">
                  {result.delta_findings.map((f, i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.04 }}
                      className="grid md:grid-cols-5 gap-3 p-4 rounded-[10px] bg-surface-secondary/20 border border-border hover:border-accent/40 transition-all"
                    >
                      <div className="md:col-span-1 flex flex-col items-center justify-center gap-1 border-b md:border-b-0 md:border-r border-border pb-2 md:pb-0 md:pr-2">
                        <DeltaBadge delta={f.impact_delta} />
                        <span className="text-[10px] text-muted uppercase tracking-wider font-mono">Impact</span>
                        <DeltaBadge delta={f.confidence_delta} />
                        <span className="text-[10px] text-muted uppercase tracking-wider font-mono">Confidence</span>
                      </div>
                      <div className="md:col-span-4 pl-0 md:pl-2">
                        <p className="font-heading text-xs font-semibold text-fg mb-2">{f.title}</p>
                        <div className="grid md:grid-cols-2 gap-3">
                          <div className="p-3 rounded-[8px] bg-surface border border-border">
                            <p className="text-[10px] text-muted font-bold uppercase tracking-wider mb-1 font-mono">A (Baseline)</p>
                            <p className="text-[12px] text-muted leading-relaxed font-body">{f.finding_a}</p>
                          </div>
                          <div className="p-3 rounded-[8px] bg-surface border border-accent/30">
                            <p className="text-[10px] text-accent font-bold uppercase tracking-wider mb-1 font-mono">B (Evaluation)</p>
                            <p className="text-[12px] text-fg leading-relaxed font-body">{f.finding_b}</p>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  ))}
                </div>
              </div>
            )}

            {/* New in B */}
            {result.new_findings_in_b.length > 0 && (
              <div className="bg-surface border border-border rounded-[12px] p-6 shadow-custom-sm">
                <h2 className="font-heading text-base font-bold text-success mb-4 flex items-center gap-2">
                  <Star size={16} />
                  Newly Emerged Findings in Synthesis B ({result.new_findings_in_b.length})
                </h2>
                <div className="space-y-2.5">
                  {result.new_findings_in_b.map((f, i) => (
                    <div key={i} className="p-3.5 rounded-[8px] bg-surface-secondary/30 border border-border">
                      <p className="font-heading text-sm font-semibold text-fg">{f.title || f.finding || 'Empirical Finding'}</p>
                      <p className="text-xs text-muted mt-1 leading-relaxed font-body">{f.detail || f.description || ''}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Dropped from A */}
            {result.dropped_findings_from_a.length > 0 && (
              <div className="bg-surface border border-border rounded-[12px] p-6 shadow-custom-sm">
                <h2 className="font-heading text-base font-bold text-accent mb-4 flex items-center gap-2">
                  <ChevronRight size={16} />
                  Findings Confined Exclusively to Synthesis A ({result.dropped_findings_from_a.length})
                </h2>
                <div className="space-y-2.5">
                  {result.dropped_findings_from_a.map((f, i) => (
                    <div key={i} className="p-3.5 rounded-[8px] bg-surface-secondary/30 border border-border">
                      <p className="font-heading text-sm font-semibold text-fg">{f.title || f.finding || 'Empirical Finding'}</p>
                      <p className="text-xs text-muted mt-1 leading-relaxed font-body">{f.detail || f.description || ''}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </motion.div>
        )}
      </div>
    </div>
  );
}
