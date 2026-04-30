import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Download, Share, Settings, AlertTriangle, Target,
  X, Loader2, ChevronRight, BarChart2
} from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { Button } from '../components/ui/Button';

// ── Types ─────────────────────────────────────────────────────────────────────
interface ChartItem {
  title: string;
  interpretation: string;
  image: string;
}

interface ReportData {
  id: string;
  filename: string;
  created_at?: string;
  report: {
    domain?: string;
    executiveSummary?: string;
    keyFindings?: { title?: string; finding?: string; detail?: string; description?: string; confidenceScore?: number }[];
    anomalies?: { column?: string; severity?: string; description?: string; businessImpact?: string }[];
    recommendations?: { action?: string; rationale?: string; priority?: string }[];
  };
  stats?: {
    shape?: { rows: number; columns: number };
    numeric_summary?: Record<string, { mean: number; std: number; min: number; max: number }>;
    missing_values?: Record<string, number>;
    statistical_anomalies?: { column: string; outlier_count: number; mean: number }[];
  };
}

// ── Severity badge ────────────────────────────────────────────────────────────
const SevBadge = ({ sev }: { sev?: string }) => {
  const s = (sev || 'medium').toLowerCase();
  const cls = s === 'high' ? 'bg-red-100 text-red-700' : s === 'low' ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700';
  return <span className={`text-[11px] font-bold px-2 py-0.5 rounded uppercase tracking-wider ${cls}`}>{s}</span>;
};

// ── Main Component ────────────────────────────────────────────────────────────
export function Report() {
  const { id } = useParams<{ id: string }>();

  const [reportData, setReportData] = useState<ReportData | null>(null);
  const [charts, setCharts] = useState<ChartItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [chartsLoading, setChartsLoading] = useState(false);
  const [error, setError] = useState('');

  // Customization state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<'colors' | 'sections' | 'export'>('colors');
  const [accentColor, setAccentColor] = useState('#1A56DB');
  const [fontColor, setFontColor] = useState('#111111');
  const [chartPalette, setChartPalette] = useState([
    '#4E79A7','#F28E2B','#E15759','#76B7B2','#59A14F',
    '#EDC949','#AF7AA1','#FF9DA7','#9C755F','#BAB0AB'
  ]);
  const [sections, setSections] = useState({
    executiveSummary: true,
    visualizations: true,
    keyFindings: true,
    anomalies: true,
    recommendations: true,
  });

  // Fetch report data
  useEffect(() => {
    if (!id) return;
    setLoading(true);
    fetch(`http://localhost:8000/api/reports/${id}`)
      .then(r => {
        if (!r.ok) throw new Error('Report not found');
        return r.json();
      })
      .then(data => {
        setReportData(data);
        setLoading(false);
        // Now fetch charts
        setChartsLoading(true);
        return fetch(`http://localhost:8000/api/charts/${id}`);
      })
      .then(r => r.json())
      .then(data => {
        setCharts(data.charts || []);
        setChartsLoading(false);
      })
      .catch(err => {
        setError(err.message || 'Failed to load report');
        setLoading(false);
        setChartsLoading(false);
      });
  }, [id]);

  if (loading) return (
    <div className="flex items-center justify-center min-h-screen">
      <Loader2 className="w-8 h-8 animate-spin text-accent" />
    </div>
  );

  if (error || !reportData) return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4">
      <p className="text-fg/60">{error || 'Report not found'}</p>
      <Link to="/library"><Button variant="outlined">Back to Library</Button></Link>
    </div>
  );

  const ai = reportData.report || {};
  const stats = reportData.stats || {};
  const shape = stats.shape || {};
  const findings = ai.keyFindings || [];
  const anomalies = ai.anomalies || [];
  const recs = ai.recommendations || [];
  const statAnomalies = stats.statistical_anomalies || [];

  return (
    <div className="w-full bg-[#FAFAFA] min-h-full py-12 px-6 font-body" style={{ color: fontColor }}>

      {/* Header */}
      <div className="max-w-[900px] mx-auto mb-10 pb-10 border-b border-border">
        <div className="text-[12px] text-fg/50 mb-3 uppercase tracking-widest">
          <Link to="/library" className="hover:text-accent transition-colors">Library</Link>
          <ChevronRight className="inline w-3 h-3 mx-1" />
          {reportData.filename}
        </div>
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
          <div>
            <h1 className="font-heading text-[36px] font-bold leading-tight max-w-[540px]" style={{ color: fontColor }}>
              {reportData.filename}
            </h1>
            {ai.domain && (
              <p className="text-[13px] mt-1 font-medium" style={{ color: accentColor }}>{ai.domain}</p>
            )}
            <p className="text-[12px] text-fg/50 mt-1">
              {shape.rows?.toLocaleString() || '—'} rows × {shape.columns || '—'} columns
              {reportData.created_at ? ` · ${reportData.created_at}` : ''}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="ghost" className="gap-2 text-fg/70">
              <Share className="w-4 h-4" /> Share
            </Button>
            <Button variant="outlined" className="gap-2" onClick={() => setIsModalOpen(true)}>
              <Settings className="w-4 h-4" /> Customize
            </Button>
            <a href={`http://localhost:8000/api/export/${id}`} target="_blank" rel="noreferrer">
              <Button variant="primary" className="gap-2" style={{ backgroundColor: accentColor }}>
                <Download className="w-4 h-4" /> Download PDF
              </Button>
            </a>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="max-w-[900px] mx-auto space-y-16">

        {/* 1. Executive Summary */}
        {sections.executiveSummary && ai.executiveSummary && (
          <section>
            <h2 className="font-heading text-[28px] font-semibold mb-5">Executive Summary</h2>
            <p className="text-[14px] leading-[1.8] opacity-90">{ai.executiveSummary}</p>
            <div className="mt-6 p-5 bg-surface rounded-r-lg" style={{ borderLeft: `4px solid ${accentColor}` }}>
              <div className="text-[11px] font-bold uppercase tracking-widest mb-1" style={{ color: accentColor }}>
                Dataset at a glance
              </div>
              <p className="text-[13px] opacity-80">
                {shape.rows?.toLocaleString()} rows · {shape.columns} columns analyzed
                {ai.domain ? ` · Domain: ${ai.domain}` : ''}
              </p>
            </div>
          </section>
        )}

        {/* 2. Data Visualizations */}
        {sections.visualizations && (
          <section>
            <h2 className="font-heading text-[28px] font-semibold mb-2">Data Visualizations</h2>
            <p className="text-[13px] text-fg/60 mb-8">
              Charts generated from your actual dataset — not templates.
            </p>

            {chartsLoading ? (
              <div className="flex items-center gap-3 py-12 text-fg/50">
                <Loader2 className="w-5 h-5 animate-spin" />
                <span className="text-[14px]">Generating charts from your data…</span>
              </div>
            ) : charts.length === 0 ? (
              <div className="flex items-center gap-3 py-10 text-fg/40">
                <BarChart2 className="w-6 h-6" />
                <span className="text-[14px]">No charts could be generated for this dataset.</span>
              </div>
            ) : (
              <div className="space-y-10">
                {charts.map((ch, i) => (
                  <div key={i} className="bg-surface rounded-[12px] p-6 border border-border/70 shadow-sm">
                    <h3 className="font-heading text-[18px] font-medium mb-4" style={{ color: fontColor }}>
                      {ch.title}
                    </h3>
                    <img
                      src={ch.image}
                      alt={ch.title}
                      className="w-full rounded-md"
                      style={{ maxHeight: 420, objectFit: 'contain' }}
                    />
                    <div className="mt-4 p-4 bg-blue-50 rounded-md border-l-4" style={{ borderLeftColor: accentColor }}>
                      <p className="text-[13px] leading-[1.7] text-fg/80">
                        <strong className="font-semibold" style={{ color: accentColor }}>Interpretation: </strong>
                        {ch.interpretation}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {/* 3. Key Findings */}
        {sections.keyFindings && findings.length > 0 && (
          <section>
            <h2 className="font-heading text-[28px] font-semibold mb-6">Key Findings</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {findings.map((f, i) => {
                const title = f.title || f.finding || `Finding ${i + 1}`;
                const detail = f.detail || f.description || '';
                const conf = f.confidenceScore;
                return (
                  <div key={i} className="bg-surface rounded-[12px] p-6 shadow-sm border border-border/50">
                    <div className="flex items-start justify-between mb-3 gap-2">
                      <h3 className="font-heading text-[18px] font-medium leading-snug">{title}</h3>
                      {conf && (
                        <span className="text-[11px] font-bold shrink-0 px-2 py-1 rounded-full bg-accent/10 text-accent">
                          {conf}%
                        </span>
                      )}
                    </div>
                    {detail && <p className="text-[13px] leading-relaxed opacity-80">{detail}</p>}
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* 4. Anomalies */}
        {sections.anomalies && (anomalies.length > 0 || statAnomalies.length > 0) && (
          <section>
            <h2 className="font-heading text-[28px] font-semibold mb-6">Anomalies Detected</h2>

            {/* Statistical anomalies table */}
            {statAnomalies.length > 0 && (
              <div className="mb-8 overflow-x-auto">
                <table className="w-full text-[13px] border-collapse">
                  <thead>
                    <tr style={{ backgroundColor: accentColor, color: '#fff' }}>
                      <th className="text-left p-3 font-medium">Column</th>
                      <th className="text-center p-3 font-medium">Outlier Rows</th>
                      <th className="text-center p-3 font-medium">Column Mean</th>
                    </tr>
                  </thead>
                  <tbody>
                    {statAnomalies.map((a, i) => (
                      <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-amber-50'}>
                        <td className="p-3 font-medium">{a.column}</td>
                        <td className="p-3 text-center text-red-600 font-bold">{a.outlier_count}</td>
                        <td className="p-3 text-center">{a.mean?.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* AI narrative anomalies */}
            <div className="space-y-5">
              {anomalies.map((a, i) => (
                <div key={i} className="pb-5 border-b border-border/50">
                  <div className="flex items-center gap-3 mb-2">
                    <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0" />
                    <h4 className="font-body text-[14px] font-bold">{a.column || 'Unknown'}</h4>
                    <SevBadge sev={a.severity} />
                  </div>
                  {a.description && (
                    <p className="text-[13px] leading-relaxed opacity-80 ml-8">{a.description}</p>
                  )}
                  {a.businessImpact && (
                    <p className="text-[12px] mt-1 ml-8 font-medium" style={{ color: accentColor }}>
                      Impact: {a.businessImpact}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* 5. Recommendations */}
        {sections.recommendations && recs.length > 0 && (
          <section>
            <h2 className="font-heading text-[28px] font-semibold mb-6">Recommendations</h2>
            <div className="bg-surface rounded-[12px] p-8 border border-border/50">
              <div className="flex items-center gap-3 mb-6">
                <Target className="w-6 h-6" style={{ color: accentColor }} />
                <h3 className="font-heading text-[20px] font-medium">Action Items</h3>
              </div>
              <ol className="list-decimal list-outside ml-5 space-y-6 text-[14px] leading-[1.7] opacity-90">
                {recs.map((rec, i) => {
                  const priority = (rec.priority || 'Medium').toUpperCase();
                  const pColor = priority === 'HIGH' ? '#DC2626' : priority === 'LOW' ? '#16A34A' : '#D97706';
                  return (
                    <li key={i} className="pl-2">
                      <div className="flex items-center gap-2 mb-1">
                        <strong className="font-semibold" style={{ color: fontColor }}>{rec.action}</strong>
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ backgroundColor: `${pColor}20`, color: pColor }}>
                          {priority}
                        </span>
                      </div>
                      {rec.rationale && <p className="opacity-70 text-[13px]">{rec.rationale}</p>}
                    </li>
                  );
                })}
              </ol>
            </div>
          </section>
        )}

      </div>

      {/* CUSTOMIZATION MODAL */}
      <AnimatePresence>
        {isModalOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/40 backdrop-blur-sm z-40"
              onClick={() => setIsModalOpen(false)}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-[580px] bg-bg rounded-[16px] shadow-2xl z-50 overflow-hidden flex flex-col max-h-[85vh]"
            >
              {/* Header */}
              <div className="px-6 py-5 border-b border-border flex justify-between items-center bg-surface">
                <h2 className="font-heading text-[22px] font-medium text-fg">Report Customization</h2>
                <button onClick={() => setIsModalOpen(false)} className="text-fg/50 hover:text-fg">
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Tabs */}
              <div className="flex border-b border-border px-6 pt-4 bg-surface/50 gap-1">
                {(['colors', 'sections', 'export'] as const).map(tab => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`px-4 py-3 text-[12px] font-medium uppercase tracking-wider border-b-2 transition-colors ${
                      activeTab === tab ? 'border-accent text-accent' : 'border-transparent text-fg/50 hover:text-fg'
                    }`}
                  >{tab}</button>
                ))}
              </div>

              {/* Tab content */}
              <div className="p-6 overflow-y-auto flex-1 text-fg space-y-6">

                {activeTab === 'colors' && (
                  <>
                    <div>
                      <h3 className="text-[11px] font-bold uppercase tracking-widest text-fg/50 mb-3">Accent Color</h3>
                      <div className="flex items-center gap-4">
                        <input type="color" value={accentColor} onChange={e => setAccentColor(e.target.value)}
                          className="w-12 h-12 cursor-pointer rounded border border-border" />
                        <div>
                          <p className="text-[13px] font-medium">Highlights, borders, labels</p>
                          <p className="text-[11px] text-fg/50 mt-0.5">Current: {accentColor}</p>
                        </div>
                      </div>
                    </div>
                    <div>
                      <h3 className="text-[11px] font-bold uppercase tracking-widest text-fg/50 mb-3">Font Color</h3>
                      <div className="flex items-center gap-4">
                        <input type="color" value={fontColor} onChange={e => setFontColor(e.target.value)}
                          className="w-12 h-12 cursor-pointer rounded border border-border" />
                        <div>
                          <p className="text-[13px] font-medium">Body & heading text</p>
                          <p className="text-[11px] text-fg/50 mt-0.5">Current: {fontColor}</p>
                        </div>
                      </div>
                    </div>
                    <div>
                      <h3 className="text-[11px] font-bold uppercase tracking-widest text-fg/50 mb-3">Chart Palette</h3>
                      <div className="flex flex-wrap gap-3">
                        {chartPalette.map((c, i) => (
                          <label key={i} className="w-9 h-9 rounded cursor-pointer shadow-sm border border-border/50 overflow-hidden relative">
                            <input type="color" value={c}
                              onChange={e => { const p = [...chartPalette]; p[i] = e.target.value; setChartPalette(p); }}
                              className="absolute opacity-0 w-full h-full cursor-pointer" />
                            <div className="w-full h-full" style={{ backgroundColor: c }} />
                          </label>
                        ))}
                      </div>
                      <button
                        className="mt-3 text-[11px] text-fg/50 hover:text-accent underline"
                        onClick={() => setChartPalette(['#4E79A7','#F28E2B','#E15759','#76B7B2','#59A14F','#EDC949','#AF7AA1','#FF9DA7','#9C755F','#BAB0AB'])}
                      >Reset to Tableau palette</button>
                    </div>
                  </>
                )}

                {activeTab === 'sections' && (
                  <div>
                    <h3 className="text-[11px] font-bold uppercase tracking-widest text-fg/50 mb-4">Visible Sections</h3>
                    <div className="space-y-1">
                      {Object.entries(sections).map(([key, val]) => (
                        <label key={key} className="flex items-center justify-between cursor-pointer p-3 hover:bg-surface rounded-md border border-transparent hover:border-border transition-colors">
                          <span className="text-[13px] capitalize">{key.replace(/([A-Z])/g, ' $1').trim()}</span>
                          <input type="checkbox" checked={val}
                            onChange={e => setSections(s => ({ ...s, [key]: e.target.checked }))}
                            className="w-4 h-4 accent-accent" />
                        </label>
                      ))}
                    </div>
                  </div>
                )}

                {activeTab === 'export' && (
                  <div className="space-y-4">
                    <p className="text-[13px] text-fg/60">The PDF is generated server-side using your uploaded data. Click below to download it.</p>
                    <a href={`http://localhost:8000/api/export/${id}`} target="_blank" rel="noreferrer" className="block">
                      <Button variant="primary" className="w-full justify-center gap-2" style={{ backgroundColor: accentColor }}>
                        <Download className="w-4 h-4" /> Download PDF Report
                      </Button>
                    </a>
                  </div>
                )}
              </div>

              <div className="px-6 py-4 border-t border-border bg-surface flex justify-end gap-3">
                <Button variant="ghost" onClick={() => setIsModalOpen(false)}>Close</Button>
                <Button onClick={() => setIsModalOpen(false)} style={{ backgroundColor: accentColor, color: '#fff' }}>
                  Apply
                </Button>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

    </div>
  );
}
