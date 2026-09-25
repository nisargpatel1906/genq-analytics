import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Download, Settings, AlertTriangle, Target,
  X, Loader2, ChevronRight, BarChart2, BookOpen,
  TrendingUp, Zap, GitBranch, Users, AlertCircle, Clock,
  Database, Star, Award, Shield
} from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { Button } from '../components/ui/Button';
import { API_URL, apiHeaders } from '../lib/api';
import { useAnalysisStore } from '../store/useAnalysisStore';
import type { ReportData, ReportSection } from '../store/useAnalysisStore';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// ── Severity badge ────────────────────────────────────────────────────────────
const SevBadge = ({ sev }: { sev?: string }) => {
  const s = (sev || 'medium').toLowerCase();
  const cls = s === 'high' ? 'bg-red-100 text-red-700' : s === 'low' ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700';
  return <span className={`text-[11px] font-bold px-2 py-0.5 rounded uppercase tracking-wider ${cls}`}>{s}</span>;
};

// ── Markdown Renderer ────────────────────────────────────────────────────────
const MarkdownBlock = ({ content }: { content: string }) => {
  return (
    <div className="prose prose-sm max-w-none text-[14px] leading-[1.8] opacity-90 prose-p:my-3 prose-headings:font-heading prose-headings:font-semibold prose-strong:font-semibold prose-strong:text-fg prose-ul:list-disc prose-ul:pl-5 prose-ol:list-decimal prose-ol:pl-5 prose-li:my-1">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
};

// ── Main Component ────────────────────────────────────────────────────────────
export function Report() {
  const { id } = useParams<{ id: string }>();

  const {
    currentReportData: reportData,
    currentReportCharts: charts,
    isReportLoading: loading,
    isChartsLoading: chartsLoading,
    reportError: error,
    loadReport,
    updateReportData,
  } = useAnalysisStore();

  const [isEditing, setIsEditing] = useState(false);
  const [editedReport, setEditedReport] = useState<ReportData['report'] | null>(null);
  const [saving, setSaving] = useState(false);

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
    causalAnalysis: true,
    strategicBrief: true,
    forecastSegments: true,
  });

  const handleStartEdit = () => {
    if (!reportData) return;
    setEditedReport(JSON.parse(JSON.stringify(reportData.report)));
    setIsEditing(true);
  };

  const handleSave = () => {
    if (!id || !editedReport) return;
    setSaving(true);
    fetch(`${API_URL}/api/reports/${id}`, {
      method: 'PUT',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ report: editedReport }),
    })
      .then(r => {
        if (!r.ok) throw new Error('Failed to save changes');
        return r.json();
      })
      .then(data => {
        updateReportData(data);
        setIsEditing(false);
        setSaving(false);
      })
      .catch(err => {
        alert(err.message || 'Failed to save changes');
        setSaving(false);
      });
  };

  const handleFindingChange = (index: number, field: string, value: any) => {
    if (!editedReport) return;
    const newFindings = [...(editedReport.keyFindings || [])];
    newFindings[index] = { ...newFindings[index], [field]: value };
    setEditedReport({ ...editedReport, keyFindings: newFindings });
  };

  const handleAnomalyChange = (index: number, field: string, value: any) => {
    if (!editedReport) return;
    const newAnomalies = [...(editedReport.anomalies || [])];
    newAnomalies[index] = { ...newAnomalies[index], [field]: value };
    setEditedReport({ ...editedReport, anomalies: newAnomalies });
  };

  const handleRecChange = (index: number, field: string, value: any) => {
    if (!editedReport) return;
    const newRecs = [...(editedReport.recommendations || [])];
    newRecs[index] = { ...newRecs[index], [field]: value };
    setEditedReport({ ...editedReport, recommendations: newRecs });
  };

  // Fetch report data
  useEffect(() => {
    if (id) {
      loadReport(id);
    }
  }, [id, loadReport]);

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
  const stats = reportData.stats;
  const shape = stats?.shape;
  const findings = ai.keyFindings || [];
  const anomalies = ai.anomalies || [];
  const recs = ai.recommendations || [];
  const statAnomalies = stats?.statistical_anomalies || [];
  // Senior Analyst Tier data
  const strategicBrief = ai.strategic_brief || {};
  const causalAnalysis = ai.causal_analysis || {};
  const forecastData = ai.forecast || {};
  const anomalyDetection = ai.anomaly_detection || {};
  const strategicRecs = ai.strategic_recommendations || strategicBrief.recommendations || [];
  const execHeadline = ai.executive_headline || strategicBrief.executive_headline || '';
  const segments = anomalyDetection.segments || [];
  // NEW agent data
  const cohortAnalysis = ai.cohort_analysis || {};
  const benchmarkAnalysis = ai.benchmark_analysis || {};
  const dataQualityGate = ai.data_quality_gate || {};
  const presentationOutline = ai.presentation_outline || {};
  const mlResults = ai.ml_predictive_modeling || {};

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
              {shape?.rows?.toLocaleString() || '—'} rows × {shape?.columns || '—'} columns
              {reportData.created_at ? ` · ${reportData.created_at}` : ''}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {isEditing ? (
              <>
                <Button variant="outlined" disabled={saving} className="gap-2 text-red-600 border-red-200 hover:bg-red-50" onClick={() => setIsEditing(false)}>
                  Cancel
                </Button>
                <Button variant="primary" disabled={saving} className="gap-2" style={{ backgroundColor: accentColor }} onClick={handleSave}>
                  {saving ? 'Saving...' : 'Save Changes'}
                </Button>
              </>
            ) : (
              <>
                <Button variant="outlined" className="gap-2" onClick={handleStartEdit}>
                  Edit Report
                </Button>
                <Button variant="outlined" className="gap-2" onClick={() => setIsModalOpen(true)}>
                  <Settings className="w-4 h-4" /> Customize
                </Button>
                <a href={`${API_URL}/api/export/${id}`} target="_blank" rel="noreferrer">
                  <Button variant="primary" className="gap-2" style={{ backgroundColor: accentColor }}>
                    <Download className="w-4 h-4" /> Download PDF
                  </Button>
                </a>
                <a href={`${API_URL}/api/export/${id}/docx`} target="_blank" rel="noreferrer">
                  <Button variant="outlined" className="gap-2 border-accent text-accent hover:bg-accent/5">
                    <Download className="w-4 h-4" /> Download DOCX
                  </Button>
                </a>
                <a href={`${API_URL}/api/export/${id}/notebook`} target="_blank" rel="noreferrer">
                  <Button variant="outlined" className="gap-2 border-emerald-600 text-emerald-700 hover:bg-emerald-50">
                    <BookOpen className="w-4 h-4" /> Download Notebook
                  </Button>
                </a>
                <a href={`${API_URL}/api/export/${id}/pptx`} target="_blank" rel="noreferrer">
                  <Button variant="outlined" className="gap-2 border-violet-500 text-violet-700 hover:bg-violet-50">
                    <Download className="w-4 h-4" /> Download PPTX {presentationOutline?.slides?.length ? `(${presentationOutline.slides.length} slides)` : ''}
                  </Button>
                </a>
                {/* Quick navigation to new pages */}
                <Link to={`/reports/${id}/insights`}>
                  <Button variant="outlined" className="gap-2 border-amber-400 text-amber-700 hover:bg-amber-50">
                    <Star className="w-4 h-4" /> Insights Feed
                  </Button>
                </Link>
                <Link to={`/reports/${id}/playground`}>
                  <Button variant="outlined" className="gap-2 border-emerald-400 text-emerald-700 hover:bg-emerald-50">
                    <Database className="w-4 h-4" /> Data Playground
                  </Button>
                </Link>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="max-w-[900px] mx-auto space-y-16">

        {/* Executive Summary — always shown */}
        {sections.executiveSummary && (
          <section>
            <h2 className="font-heading text-[28px] font-semibold mb-5">Executive Summary</h2>
            {isEditing ? (
              <textarea
                className="w-full min-h-[150px] p-4 border border-border rounded-lg bg-white text-[14px] leading-[1.7] focus:outline-none focus:ring-2 focus:ring-accent/50"
                value={editedReport?.executiveSummary || ''}
                onChange={e => setEditedReport(prev => prev ? { ...prev, executiveSummary: e.target.value } : null)}
              />
            ) : (
              ai.executiveSummary && <MarkdownBlock content={ai.executiveSummary} />
            )}
            {/* Executive Headline Hero Banner — from Strategic Advisor */}
            {execHeadline && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="mt-5 p-5 rounded-[12px] border border-amber-200/80 bg-gradient-to-r from-amber-50 to-orange-50 shadow-sm"
              >
                <div className="flex items-start gap-3">
                  <Zap className="w-5 h-5 text-amber-600 mt-0.5 shrink-0" />
                  <div>
                    <div className="text-[10px] font-bold uppercase tracking-widest text-amber-600 mb-1">Strategic Headline</div>
                    <p className="text-[15px] font-semibold text-amber-900 leading-snug">{execHeadline}</p>
                  </div>
                </div>
              </motion.div>
            )}
            <div className="mt-6 p-5 bg-surface rounded-r-lg" style={{ borderLeft: `4px solid ${accentColor}` }}>
              <div className="text-[11px] font-bold uppercase tracking-widest mb-1" style={{ color: accentColor }}>
                Dataset at a glance
              </div>
              <p className="text-[13px] opacity-80">
                {shape?.rows?.toLocaleString()} rows · {shape?.columns} columns analyzed
                {ai.domain ? ` · Domain: ${ai.domain}` : ''}
              </p>
            </div>
          </section>
        )}

        {/* Methodology — show if present */}
        {ai.methodology && (
          <section>
            <h2 className="font-heading text-[22px] font-semibold mb-4 text-fg/70">Methodology</h2>
            <div className="bg-surface p-5 rounded-lg border border-border/50">
              <MarkdownBlock content={ai.methodology} />
            </div>
          </section>
        )}

        {/* Data Visualizations */}
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

        {/* ── AGENT THOUGHTS ───────────────────────────────────────────────── */}
        {ai.report_planning && (
          <section>
            <div className="bg-blue-50/50 rounded-lg border border-blue-100 p-5 shadow-sm">
              <div className="flex items-center gap-2 mb-3">
                <Target className="w-5 h-5 text-blue-600" />
                <h3 className="font-heading text-[16px] font-semibold text-blue-900">Agent Analysis Strategy</h3>
              </div>
              <div className="space-y-4">
                {ai.report_planning.data_relevance_evaluation && (
                  <div>
                    <h4 className="text-[11px] font-bold uppercase tracking-wider text-blue-800/70 mb-1">Data Evaluation</h4>
                    <p className="text-[13px] leading-relaxed text-blue-900/80">
                      {ai.report_planning.data_relevance_evaluation}
                    </p>
                  </div>
                )}
                {ai.report_planning.narrative_flow_strategy && (
                  <div>
                    <h4 className="text-[11px] font-bold uppercase tracking-wider text-blue-800/70 mb-1">Narrative Strategy</h4>
                    <p className="text-[13px] leading-relaxed text-blue-900/80">
                      {ai.report_planning.narrative_flow_strategy}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

        {/* ── DYNAMIC SECTIONS ─────────────────────────────────────────────── */}
        {ai.reportSections && ai.reportSections.length > 0 ? (
          <>
            {ai.reportSections.map((section: ReportSection, idx: number) => {
              if (section.type === 'findings_group') {
                const sectionFindings = section.findings || [];
                if (sectionFindings.length === 0 && !section.narrative) return null;
                return (
                  <section key={idx}>
                    <h2 className="font-heading text-[28px] font-semibold mb-4">{section.title}</h2>
                    {section.narrative && (
                      <div className="mb-6"><MarkdownBlock content={section.narrative} /></div>
                    )}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      {sectionFindings.map((f, i) => (
                        <div key={i} className="bg-surface rounded-[12px] p-6 shadow-sm border border-border/50 flex flex-col justify-between">
                          <div className="flex items-start justify-between mb-3 gap-2">
                            <h3 className="font-heading text-[18px] font-medium leading-snug">{f.title || `Finding ${i + 1}`}</h3>
                            {f.confidence && (
                              <span className="text-[11px] font-bold shrink-0 px-2 py-1 rounded-full bg-accent/10 text-accent">
                                {f.confidence}%
                              </span>
                            )}
                          </div>
                          {f.detail && <div className="text-[13px] leading-relaxed opacity-80"><MarkdownBlock content={f.detail} /></div>}
                          {f.effect_size && (
                            <div className="mt-3 p-3 bg-blue-50 rounded-md">
                              <p className="text-[11px] font-bold uppercase tracking-wider text-blue-600 mb-1">Effect Size</p>
                              <p className="text-[12px] text-fg/70">{f.effect_size}</p>
                            </div>
                          )}
                          {f.practical_significance && (
                            <p className="text-[12px] mt-2 text-fg/60 italic">{f.practical_significance}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </section>
                );
              }

              if (section.type === 'data_overview' || section.type === 'trend_analysis' || section.type === 'comparison' || section.type === 'narrative') {
                if (!section.content) return null;
                return (
                  <section key={idx}>
                    <h2 className="font-heading text-[28px] font-semibold mb-5">{section.title}</h2>
                    <MarkdownBlock content={section.content} />
                  </section>
                );
              }

              if (section.type === 'data_table') {
                const headers = section.headers || [];
                const rows = section.rows || [];
                if (headers.length === 0 || rows.length === 0) return null;
                return (
                  <section key={idx}>
                    <h2 className="font-heading text-[28px] font-semibold mb-6">{section.title}</h2>
                    <div className="overflow-x-auto rounded-lg border border-border/70 shadow-sm">
                      <table className="w-full text-[13px] border-collapse bg-white">
                        <thead>
                          <tr className="bg-surface border-b border-border text-left">
                            {headers.map((h, i) => (
                              <th key={i} className="px-4 py-3 font-semibold text-fg/80 uppercase tracking-wider text-[11px]">
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border/50">
                          {rows.map((row, rIdx) => (
                            <tr key={rIdx} className="hover:bg-surface/50 transition-colors">
                              {row.map((cell, cIdx) => (
                                <td key={cIdx} className="px-4 py-3 text-fg/90">
                                  {cell}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                );
              }

              if (section.type === 'anomalies') {
                const sectionAnomalies = section.anomalies || [];
                if (sectionAnomalies.length === 0) return null;
                return (
                  <section key={idx}>
                    <h2 className="font-heading text-[28px] font-semibold mb-6">{section.title}</h2>
                    <div className="space-y-5">
                      {sectionAnomalies.map((a, i) => (
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
                );
              }

              if (section.type === 'recommendations') {
                const sectionRecs = section.recommendations || [];
                if (sectionRecs.length === 0) return null;
                return (
                  <section key={idx}>
                    <h2 className="font-heading text-[28px] font-semibold mb-6">{section.title}</h2>
                    <div className="bg-surface rounded-[12px] p-8 border border-border/50">
                      <div className="flex items-center gap-3 mb-6">
                        <Target className="w-6 h-6" style={{ color: accentColor }} />
                        <h3 className="font-heading text-[20px] font-medium">Action Items</h3>
                      </div>
                      <ol className="list-decimal list-outside ml-5 space-y-6 text-[14px] leading-[1.7] opacity-90">
                        {sectionRecs.map((rec, i) => {
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
                              {rec.rationale && <div className="opacity-70 text-[13px]"><MarkdownBlock content={rec.rationale} /></div>}
                              {rec.expected_outcome && (
                                <p className="text-[12px] mt-1 italic" style={{ color: accentColor }}>
                                  Expected: {rec.expected_outcome}
                                </p>
                              )}
                            </li>
                          );
                        })}
                      </ol>
                    </div>
                  </section>
                );
              }

              return null;
            })}

            {/* Limitations */}
            {ai.limitations && ai.limitations.length > 0 && (
              <section>
                <h2 className="font-heading text-[22px] font-semibold mb-4 text-fg/70">Limitations & Caveats</h2>
                <ul className="space-y-2">
                  {ai.limitations.map((lim: string, i: number) => (
                    <li key={i} className="text-[13px] leading-relaxed opacity-70 flex items-start gap-2">
                      <span className="text-fg/40 mt-0.5">•</span>
                      <span>{lim}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        ) : (
          /* ── LEGACY FALLBACK: hardcoded sections ─────────────────────── */
          <>
            {/* Key Findings (legacy) */}
            {sections.keyFindings && (isEditing ? (editedReport?.keyFindings || []) : findings).length > 0 && (
              <section>
                <h2 className="font-heading text-[28px] font-semibold mb-6">Key Findings</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {(isEditing ? (editedReport?.keyFindings || []) : findings).map((f, i) => {
                    const title = f.title || f.finding || `Finding ${i + 1}`;
                    const detail = f.detail || f.description || '';
                    const conf = f.confidenceScore || f.confidence;
                    return (
                      <div key={i} className="bg-surface rounded-[12px] p-6 shadow-sm border border-border/50 flex flex-col justify-between">
                        {isEditing ? (
                          <div className="space-y-3 w-full">
                            <div>
                              <label className="text-[11px] font-bold uppercase tracking-wider text-fg/40 mb-1 block">Title</label>
                              <input
                                type="text"
                                className="w-full p-2 border border-border rounded bg-white text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/50"
                                value={title}
                                onChange={e => handleFindingChange(i, f.title !== undefined ? 'title' : 'finding', e.target.value)}
                              />
                            </div>
                            <div>
                              <label className="text-[11px] font-bold uppercase tracking-wider text-fg/40 mb-1 block">Detail</label>
                              <textarea
                                className="w-full p-2 border border-border rounded bg-white text-[13px] min-h-[80px] focus:outline-none focus:ring-2 focus:ring-accent/50"
                                value={detail}
                                onChange={e => handleFindingChange(i, f.detail !== undefined ? 'detail' : 'description', e.target.value)}
                              />
                            </div>
                            <div>
                              <label className="text-[11px] font-bold uppercase tracking-wider text-fg/40 mb-1 block">AI Confidence (%)</label>
                              <input
                                type="number"
                                className="w-full p-2 border border-border rounded bg-white text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/50"
                                value={conf || 0}
                                onChange={e => handleFindingChange(i, 'confidenceScore', parseInt(e.target.value) || 0)}
                              />
                            </div>
                          </div>
                        ) : (
                          <>
                            <div className="flex items-start justify-between mb-3 gap-2">
                              <h3 className="font-heading text-[18px] font-medium leading-snug">{title}</h3>
                              {conf && (
                                <span className="text-[11px] font-bold shrink-0 px-2 py-1 rounded-full bg-accent/10 text-accent">
                                  {conf}%
                                </span>
                              )}
                            </div>
                            {detail && <p className="text-[13px] leading-relaxed opacity-80">{detail}</p>}
                            {f.effect_size && (
                              <div className="mt-3 p-3 bg-blue-50 rounded-md">
                                <p className="text-[11px] font-bold uppercase tracking-wider text-blue-600 mb-1">Effect Size</p>
                                <p className="text-[12px] text-fg/70">{f.effect_size}</p>
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {/* Anomalies (legacy) */}
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
                  {(isEditing ? (editedReport?.anomalies || []) : anomalies).map((a, i) => (
                    <div key={i} className="pb-5 border-b border-border/50">
                      {isEditing ? (
                        <div className="space-y-3 p-4 bg-surface rounded-lg border border-border/50 ml-8">
                          <div className="flex items-center gap-3">
                            <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0" />
                            <span className="text-[13px] font-bold">Column: {a.column || 'Unknown'}</span>
                            <select
                              className="p-1 border border-border rounded bg-white text-[12px] focus:outline-none focus:ring-2 focus:ring-accent/50"
                              value={a.severity || 'medium'}
                              onChange={e => handleAnomalyChange(i, 'severity', e.target.value)}
                            >
                              <option value="low">LOW</option>
                              <option value="medium">MEDIUM</option>
                              <option value="high">HIGH</option>
                            </select>
                          </div>
                          <div>
                            <label className="text-[11px] font-bold uppercase tracking-wider text-fg/40 mb-1 block">Description</label>
                            <textarea
                              className="w-full p-2 border border-border rounded bg-white text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/50"
                              value={a.description || ''}
                              onChange={e => handleAnomalyChange(i, 'description', e.target.value)}
                            />
                          </div>
                          <div>
                            <label className="text-[11px] font-bold uppercase tracking-wider text-fg/40 mb-1 block">Business Impact</label>
                            <input
                              type="text"
                              className="w-full p-2 border border-border rounded bg-white text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/50"
                              value={a.businessImpact || ''}
                              onChange={e => handleAnomalyChange(i, 'businessImpact', e.target.value)}
                            />
                          </div>
                        </div>
                      ) : (
                        <>
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
                        </>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Recommendations (legacy) */}
            {sections.recommendations && (isEditing ? (editedReport?.recommendations || []) : recs).length > 0 && (
              <section>
                <h2 className="font-heading text-[28px] font-semibold mb-6">Recommendations</h2>
                <div className="bg-surface rounded-[12px] p-8 border border-border/50">
                  <div className="flex items-center gap-3 mb-6">
                    <Target className="w-6 h-6" style={{ color: accentColor }} />
                    <h3 className="font-heading text-[20px] font-medium">Action Items</h3>
                  </div>
                  {isEditing ? (
                    <div className="space-y-6">
                      {(editedReport?.recommendations || []).map((rec, i) => (
                        <div key={i} className="p-4 bg-bg rounded-lg border border-border/50 space-y-3">
                          <div className="flex flex-wrap items-center gap-3">
                            <span className="text-[13px] font-bold">Item {i + 1}</span>
                            <select
                              className="p-1 border border-border rounded bg-white text-[12px] focus:outline-none focus:ring-2 focus:ring-accent/50"
                              value={rec.priority || 'Medium'}
                              onChange={e => handleRecChange(i, 'priority', e.target.value)}
                            >
                              <option value="Low">LOW</option>
                              <option value="Medium">MEDIUM</option>
                              <option value="High">HIGH</option>
                            </select>
                          </div>
                          <div>
                            <label className="text-[11px] font-bold uppercase tracking-wider text-fg/40 mb-1 block">Action</label>
                            <input
                              type="text"
                              className="w-full p-2 border border-border rounded bg-white text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/50"
                              value={rec.action || ''}
                              onChange={e => handleRecChange(i, 'action', e.target.value)}
                            />
                          </div>
                          <div>
                            <label className="text-[11px] font-bold uppercase tracking-wider text-fg/40 mb-1 block">Rationale</label>
                            <textarea
                              className="w-full p-2 border border-border rounded bg-white text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/50"
                              value={rec.rationale || ''}
                              onChange={e => handleRecChange(i, 'rationale', e.target.value)}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
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
                            {rec.rationale && <div className="opacity-70 text-[13px]"><MarkdownBlock content={rec.rationale} /></div>}
                            {rec.expected_outcome && (
                              <p className="text-[12px] mt-1 italic" style={{ color: accentColor }}>
                                Expected: {rec.expected_outcome}
                              </p>
                            )}
                          </li>
                        );
                      })}
                    </ol>
                  )}
                </div>
              </section>
            )}
          </>
        )}

        {/* ═══════════════════════════════════════════════════════════════════ */}
        {/* SENIOR ANALYST TIER SECTIONS                                       */}
        {/* ═══════════════════════════════════════════════════════════════════ */}

        {/* Causal Analysis */}
        {sections.causalAnalysis && causalAnalysis.causal_audit && causalAnalysis.causal_audit.length > 0 && (
          <section>
            <div className="flex items-center gap-3 mb-2">
              <GitBranch className="w-6 h-6" style={{ color: accentColor }} />
              <h2 className="font-heading text-[28px] font-semibold">Causal Analysis</h2>
            </div>
            <p className="text-[13px] text-fg/60 mb-8">Going beyond correlation — each finding is classified by causal strength.</p>

            {/* Causal Chain highlight */}
            {causalAnalysis.causal_chain && (
              <div className="mb-8 p-5 rounded-[12px] border border-violet-200 bg-violet-50/60">
                <div className="text-[10px] font-bold uppercase tracking-widest text-violet-600 mb-2">Dominant Causal Chain</div>
                <div className="flex flex-wrap gap-2 items-center">
                  {(causalAnalysis.causal_chain.chain || []).map((step: string, i: number) => (
                    <span key={i} className="flex items-center gap-2">
                      <span className="text-[13px] font-medium text-violet-900 bg-white px-3 py-1 rounded-full border border-violet-200">{step}</span>
                      {i < (causalAnalysis.causal_chain.chain || []).length - 1 && <ChevronRight className="w-4 h-4 text-violet-400" />}
                    </span>
                  ))}
                </div>
                {causalAnalysis.causal_chain.business_impact && (
                  <p className="mt-3 text-[13px] text-violet-800/80 italic">{causalAnalysis.causal_chain.business_impact}</p>
                )}
              </div>
            )}

            {/* Causal audit cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {causalAnalysis.causal_audit.map((item: any, i: number) => {
                const cls: Record<string, string> = {
                  likely_causal: 'bg-green-50 border-green-200 text-green-700',
                  plausible_association: 'bg-blue-50 border-blue-200 text-blue-700',
                  spurious_correlation: 'bg-red-50 border-red-200 text-red-700',
                  confounded: 'bg-amber-50 border-amber-200 text-amber-700',
                };
                const badge = (cls[item.classification] || 'bg-gray-50 border-gray-200 text-gray-700');
                const label: Record<string, string> = {
                  likely_causal: 'Likely Causal',
                  plausible_association: 'Association',
                  spurious_correlation: 'Spurious',
                  confounded: 'Confounded',
                };
                return (
                  <div key={i} className="bg-surface rounded-[12px] p-5 border border-border/50 shadow-sm">
                    <div className="flex items-start justify-between gap-2 mb-3">
                      <p className="text-[13px] font-medium text-fg leading-snug">{item.finding}</p>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border shrink-0 ${badge}`}>
                        {label[item.classification] || item.classification}
                      </span>
                    </div>
                    {item.reasoning && (
                      <p className="text-[12px] text-fg/60 leading-relaxed">{item.reasoning}</p>
                    )}
                    <div className="flex items-center justify-between mt-3">
                      <span className={`text-[10px] font-bold uppercase tracking-wider ${
                        item.confidence === 'High' ? 'text-green-600' :
                        item.confidence === 'Low' ? 'text-red-500' : 'text-amber-600'
                      }`}>Confidence: {item.confidence}</span>
                      {item.confounders?.length > 0 && (
                        <span className="text-[10px] text-fg/40">Confounders: {item.confounders.slice(0,2).join(', ')}</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Causal summary */}
            {causalAnalysis.causal_summary && (
              <div className="mt-8 p-5 bg-surface rounded-[12px] border border-border/50">
                <h3 className="font-heading text-[16px] font-semibold mb-3">Causal Narrative</h3>
                <MarkdownBlock content={causalAnalysis.causal_summary} />
              </div>
            )}
          </section>
        )}

        {/* Strategic Brief */}
        {sections.strategicBrief && (strategicRecs.length > 0 || strategicBrief.situation) && (
          <section>
            <div className="flex items-center gap-3 mb-2">
              <Target className="w-6 h-6" style={{ color: accentColor }} />
              <h2 className="font-heading text-[28px] font-semibold">Strategic Brief</h2>
            </div>
            <p className="text-[13px] text-fg/60 mb-8">Situation → Complication → Resolution framework.</p>

            {/* Situation */}
            {strategicBrief.situation && (
              <div className="mb-6 p-5 bg-surface rounded-[12px] border border-border/50">
                <div className="text-[10px] font-bold uppercase tracking-widest text-fg/40 mb-2">Situation</div>
                <p className="text-[14px] leading-relaxed text-fg/90">{strategicBrief.situation}</p>
              </div>
            )}

            {/* Complications */}
            {strategicBrief.complication && strategicBrief.complication.length > 0 && (
              <div className="mb-8 space-y-3">
                <div className="text-[10px] font-bold uppercase tracking-widest text-fg/40 mb-2">Critical Complications</div>
                {strategicBrief.complication.map((c: any, i: number) => (
                  <div key={i} className={`flex gap-3 p-4 rounded-[10px] border ${
                    c.severity === 'Critical' ? 'bg-red-50 border-red-200' :
                    c.severity === 'High' ? 'bg-amber-50 border-amber-200' : 'bg-blue-50 border-blue-200'
                  }`}>
                    <AlertCircle className={`w-4 h-4 mt-0.5 shrink-0 ${
                      c.severity === 'Critical' ? 'text-red-600' :
                      c.severity === 'High' ? 'text-amber-600' : 'text-blue-600'
                    }`} />
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <p className="text-[13px] font-semibold text-fg">{c.issue}</p>
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded uppercase ${
                          c.severity === 'Critical' ? 'bg-red-100 text-red-700' :
                          c.severity === 'High' ? 'bg-amber-100 text-amber-700' : 'bg-blue-100 text-blue-700'
                        }`}>{c.severity}</span>
                      </div>
                      {c.evidence && <p className="text-[12px] text-fg/60">{c.evidence}</p>}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Recommendations */}
            {strategicRecs.length > 0 && (
              <div className="space-y-4">
                <div className="text-[10px] font-bold uppercase tracking-widest text-fg/40 mb-2">Prioritised Actions</div>
                {strategicRecs.map((rec: any, i: number) => {
                  const priorityColors: Record<string, string> = {
                    Immediate: '#DC2626', 'Short-term': '#D97706', Strategic: '#2563EB'
                  };
                  const effortColors: Record<string, string> = { Low: '#16A34A', Medium: '#D97706', High: '#DC2626' };
                  const pColor = priorityColors[rec.priority] || '#6B7280';
                  const eColor = effortColors[rec.effort] || '#6B7280';
                  return (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.05 }}
                      className="bg-surface rounded-[12px] border border-border/50 shadow-sm overflow-hidden"
                    >
                      <div className="p-5">
                        <div className="flex items-start justify-between gap-3 mb-3">
                          <div className="flex items-center gap-2">
                            <span className="w-6 h-6 rounded-full bg-accent/10 text-accent text-[12px] font-bold flex items-center justify-center shrink-0">{i + 1}</span>
                            <h4 className="text-[14px] font-semibold text-fg leading-snug">{rec.action}</h4>
                          </div>
                          <div className="flex gap-2 shrink-0">
                            <span className="text-[10px] font-bold px-2 py-0.5 rounded" style={{ backgroundColor: `${pColor}20`, color: pColor }}>
                              {rec.priority}
                            </span>
                            {rec.effort && (
                              <span className="text-[10px] font-bold px-2 py-0.5 rounded" style={{ backgroundColor: `${eColor}15`, color: eColor }}>
                                {rec.effort} effort
                              </span>
                            )}
                          </div>
                        </div>
                        {rec.evidence_basis && (
                          <p className="text-[12px] text-fg/60 mb-2"><span className="font-semibold">Evidence: </span>{rec.evidence_basis}</p>
                        )}
                        {rec.expected_impact && (
                          <p className="text-[12px] font-medium" style={{ color: accentColor }}>
                            Impact: {rec.expected_impact}
                          </p>
                        )}
                      </div>
                      {(rec.kpi_to_track || rec.risk) && (
                        <div className="flex gap-0 border-t border-border/50 divide-x divide-border/50">
                          {rec.kpi_to_track && (
                            <div className="flex-1 px-4 py-2">
                              <div className="text-[10px] font-bold uppercase tracking-wider text-fg/40 mb-0.5">KPI to Track</div>
                              <p className="text-[12px] text-fg/80">{rec.kpi_to_track}</p>
                            </div>
                          )}
                          {rec.risk && (
                            <div className="flex-1 px-4 py-2">
                              <div className="text-[10px] font-bold uppercase tracking-wider text-amber-600/70 mb-0.5">Risk</div>
                              <p className="text-[12px] text-fg/70">{rec.risk}</p>
                            </div>
                          )}
                        </div>
                      )}
                    </motion.div>
                  );
                })}
              </div>
            )}

            {/* Forecast scenario */}
            {strategicBrief.forecast_scenario && (
              <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-4">
                {[
                  { key: 'no_action_30d', label: '30-Day Outlook', icon: Clock, color: '#D97706' },
                  { key: 'no_action_90d', label: '90-Day Outlook', icon: TrendingUp, color: '#DC2626' },
                  { key: 'worst_case', label: 'Worst Case', icon: AlertTriangle, color: '#7C3AED' },
                ].map(({ key, label, icon: Icon, color }) => (
                  strategicBrief.forecast_scenario[key] && (
                    <div key={key} className="p-4 bg-surface rounded-[10px] border border-border/50">
                      <div className="flex items-center gap-2 mb-2">
                        <Icon className="w-4 h-4" style={{ color }} />
                        <div className="text-[10px] font-bold uppercase tracking-widest" style={{ color }}>{label}</div>
                      </div>
                      <p className="text-[12px] text-fg/70 leading-relaxed">{strategicBrief.forecast_scenario[key]}</p>
                    </div>
                  )
                ))}
              </div>
            )}
          </section>
        )}

        {/* Forecast & Segment Intelligence */}
        {sections.forecastSegments && (segments.length > 0 || (forecastData.trend_direction && !forecastData.skipped)) && (
          <section>
            <div className="flex items-center gap-3 mb-2">
              <Users className="w-6 h-6" style={{ color: accentColor }} />
              <h2 className="font-heading text-[28px] font-semibold">Segments & Forecast</h2>
            </div>
            <p className="text-[13px] text-fg/60 mb-8">Auto-detected clusters and forward projections from your data.</p>

            {/* Forecast summary card */}
            {forecastData.trend_direction && !forecastData.skipped && (
              <div className="mb-8 p-5 rounded-[12px] border border-teal-200 bg-teal-50/60">
                <div className="text-[10px] font-bold uppercase tracking-widest text-teal-600 mb-3">Trend Analysis</div>
                <div className="flex flex-wrap gap-6">
                  <div>
                    <div className="text-[11px] text-fg/50 uppercase tracking-wide">Direction</div>
                    <div className="text-[18px] font-bold text-teal-900 capitalize">{forecastData.trend_direction}</div>
                  </div>
                  {forecastData.trend_slope_per_period != null && (
                    <div>
                      <div className="text-[11px] text-fg/50 uppercase tracking-wide">Slope / Period</div>
                      <div className="text-[18px] font-bold text-teal-900">{Number(forecastData.trend_slope_per_period).toFixed(3)}</div>
                    </div>
                  )}
                  {forecastData.seasonality_detected && (
                    <div>
                      <div className="text-[11px] text-fg/50 uppercase tracking-wide">Seasonality</div>
                      <div className="text-[18px] font-bold text-teal-900">{forecastData.seasonality_period ?? 'Detected'}</div>
                    </div>
                  )}
                  {forecastData.anomalies_detected?.length > 0 && (
                    <div>
                      <div className="text-[11px] text-fg/50 uppercase tracking-wide">Anomalous Points</div>
                      <div className="text-[18px] font-bold text-red-600">{forecastData.anomalies_detected.length}</div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Segment cards */}
            {segments.length > 0 && (
              <>
                <div className="text-[10px] font-bold uppercase tracking-widest text-fg/40 mb-4">Data Segments ({segments.length} clusters)</div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {segments.map((seg: any, i: number) => {
                    const segColors = ['#4E79A7', '#F28E2B', '#59A14F', '#E15759', '#AF7AA1'];
                    const c = segColors[i % segColors.length];
                    return (
                      <div key={i} className="bg-surface rounded-[12px] p-5 border border-border/50 shadow-sm">
                        <div className="flex items-center justify-between mb-3">
                          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: c }} />
                          <span className="text-[11px] font-bold text-fg/40">{seg.pct_of_dataset?.toFixed(1)}%</span>
                        </div>
                        <div className="text-[16px] font-bold text-fg mb-1">{seg.size?.toLocaleString()} records</div>
                        <p className="text-[12px] text-fg/60 leading-relaxed">{seg.description}</p>
                        {seg.profile && Object.keys(seg.profile).length > 0 && (
                          <div className="mt-3 pt-3 border-t border-border/50 space-y-1">
                            {Object.entries(seg.profile).slice(0, 3).map(([k, v]: [string, any]) => (
                              <div key={k} className="flex justify-between">
                                <span className="text-[11px] text-fg/50 truncate">{k}</span>
                                <span className="text-[11px] font-medium text-fg/80">{typeof v === 'number' ? v.toFixed(2) : String(v)}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Anomaly rate badge */}
                {anomalyDetection.anomaly_rate_pct != null && (
                  <div className="mt-6 p-4 rounded-[10px] border border-red-200 bg-red-50/50 flex items-center gap-4">
                    <AlertTriangle className="w-5 h-5 text-red-500 shrink-0" />
                    <div>
                      <div className="text-[13px] font-semibold text-red-800">
                        {anomalyDetection.anomaly_rate_pct.toFixed(1)}% anomaly rate detected across {anomalyDetection.total_anomalies} records
                      </div>
                      {anomalyDetection.anomaly_columns_ranked?.length > 0 && (
                        <p className="text-[12px] text-red-700/70 mt-0.5">
                          Highest-risk columns: {anomalyDetection.anomaly_columns_ranked.slice(0, 3).join(', ')}
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </section>
        )}

      </div>


        {/* DATA QUALITY GATE */}
        {dataQualityGate && dataQualityGate.score !== undefined && (
          <section>
            <div className="flex items-center gap-2 mb-5">
              <Shield className="w-5 h-5" style={{ color: accentColor }} />
              <h2 className="font-heading text-[24px] font-semibold">Data Quality Gate</h2>
            </div>
            <div className="p-5 rounded-[12px] border border-border bg-white shadow-sm">
              <div className="flex items-center gap-6 mb-4">
                <div className="text-center">
                  <div className={`text-[48px] font-black leading-none ${dataQualityGate.score >= 60 ? 'text-emerald-600' : dataQualityGate.score >= 40 ? 'text-amber-500' : 'text-red-600'}`}>
                    {dataQualityGate.score}
                  </div>
                  <div className="text-[11px] text-fg/40 mt-1">/ 100</div>
                </div>
                <div className="flex-1">
                  <span className={`inline-flex items-center gap-1 px-3 py-1 rounded-full text-[12px] font-bold mb-2 ${dataQualityGate.decision === 'PASS' ? 'bg-emerald-100 text-emerald-700' : dataQualityGate.decision === 'WARN' ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700'}`}>
                    {dataQualityGate.decision}
                  </span>
                  <div className="w-full bg-gray-100 rounded-full h-2 mt-1">
                    <div className="h-2 rounded-full" style={{ width: `${dataQualityGate.score}%`, backgroundColor: dataQualityGate.score >= 60 ? '#22c55e' : dataQualityGate.score >= 40 ? '#f59e0b' : '#ef4444' }} />
                  </div>
                </div>
              </div>
              {dataQualityGate.issues && dataQualityGate.issues.length > 0 && (
                <div className="space-y-2 mt-3 pt-3 border-t border-border">
                  {dataQualityGate.issues.map((issue: any, i: number) => (
                    <div key={i} className="flex items-start gap-2 text-[13px]">
                      <AlertTriangle className="w-4 h-4 text-amber-500 mt-0.5 shrink-0" />
                      <span className="text-fg/70">{issue.description || String(issue)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}

        {/* COHORT ANALYSIS */}
        {cohortAnalysis && cohortAnalysis.summary && (
          <section>
            <div className="flex items-center gap-2 mb-5">
              <Users className="w-5 h-5" style={{ color: accentColor }} />
              <h2 className="font-heading text-[24px] font-semibold">Cohort & Retention Analysis</h2>
            </div>
            <div className="p-5 rounded-[12px] border border-border bg-white shadow-sm space-y-4">
              <p className="text-[14px] leading-[1.75] text-fg/80">{cohortAnalysis.summary}</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {cohortAnalysis.churn_rate_overall !== undefined && (
                  <div className="p-3 rounded-lg bg-red-50 border border-red-100 text-center">
                    <p className="text-[22px] font-black text-red-600">{(cohortAnalysis.churn_rate_overall * 100).toFixed(1)}%</p>
                    <p className="text-[11px] text-red-500 mt-0.5">Overall Churn Rate</p>
                  </div>
                )}
                {cohortAnalysis.avg_retention_week1 !== undefined && (
                  <div className="p-3 rounded-lg bg-emerald-50 border border-emerald-100 text-center">
                    <p className="text-[22px] font-black text-emerald-600">{(cohortAnalysis.avg_retention_week1 * 100).toFixed(1)}%</p>
                    <p className="text-[11px] text-emerald-500 mt-0.5">Week 1 Retention</p>
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

        {/* BENCHMARKING */}
        {benchmarkAnalysis && benchmarkAnalysis.benchmark_summary && (
          <section>
            <div className="flex items-center gap-2 mb-5">
              <Award className="w-5 h-5" style={{ color: accentColor }} />
              <h2 className="font-heading text-[24px] font-semibold">Industry Benchmarking</h2>
            </div>
            <div className="space-y-3">
              <div className="p-4 rounded-[12px] border border-amber-200/60 bg-amber-50/60">
                <p className="text-[14px] text-fg/80 leading-[1.75]">{benchmarkAnalysis.benchmark_summary}</p>
              </div>
              {benchmarkAnalysis.benchmarks && benchmarkAnalysis.benchmarks.map((b: any, i: number) => {
                const verdictColor = b.verdict && b.verdict.includes('Above') ? '#22c55e' : b.verdict && b.verdict.includes('Below') ? '#ef4444' : '#f59e0b';
                return (
                  <div key={i} className="p-4 rounded-lg border border-border bg-white flex items-start justify-between gap-4">
                    <div className="flex-1">
                      <p className="text-[14px] font-semibold">{b.metric_name}</p>
                      <p className="text-[12px] text-fg/50 mt-0.5">Observed: <strong>{b.observed_value}</strong> vs Industry: {b.industry_average}</p>
                    </div>
                    <span className="text-[11px] font-bold px-2.5 py-1 rounded-full shrink-0" style={{ backgroundColor: verdictColor + '20', color: verdictColor }}>{b.verdict}</span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* ML PREDICTIVE MODELING */}
        {mlResults && mlResults.summary && (
          <section>
            <div className="flex items-center gap-2 mb-5">
              <BarChart2 className="w-5 h-5" style={{ color: accentColor }} />
              <h2 className="font-heading text-[24px] font-semibold">ML Predictive Modeling</h2>
            </div>
            <div className="p-5 rounded-[12px] border border-border bg-white shadow-sm space-y-4">
              <div>
                <p className="text-[14px] font-semibold">{mlResults.model_name || 'Trained Model'} — Target: {mlResults.target_column}</p>
                <p className="text-[14px] leading-[1.75] text-fg/80 mt-2">{mlResults.summary}</p>
              </div>
              {mlResults.feature_importances && mlResults.feature_importances.length > 0 && (
                <div className="pt-3 border-t border-border">
                  <p className="text-[12px] font-semibold text-fg/60 uppercase tracking-wider mb-2">Top Predictive Drivers</p>
                  <div className="space-y-2">
                    {mlResults.feature_importances.slice(0, 5).map((fi: any, i: number) => {
                      const maxImp = mlResults.feature_importances[0]?.importance || 1;
                      const pct = Math.round((fi.importance / maxImp) * 100);
                      return (
                        <div key={i} className="flex items-center gap-3">
                          <span className="text-[12px] text-fg/70 w-40 shrink-0 truncate">{fi.feature}</span>
                          <div className="flex-1 bg-gray-100 rounded-full h-1.5">
                            <div className="h-1.5 rounded-full" style={{ width: pct + '%', backgroundColor: accentColor }} />
                          </div>
                          <span className="text-[11px] font-mono text-fg/50 w-12 text-right">{typeof fi.importance === 'number' ? fi.importance.toFixed(3) : fi.importance}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </section>
        )}

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
                    <a href={`${API_URL}/api/export/${id}`} target="_blank" rel="noreferrer" className="block">
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
