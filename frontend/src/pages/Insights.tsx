import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  TrendingUp, Brain, GitBranch, Users, Zap, BarChart2,
  Activity, Search, ChevronRight, Star, Target,
  AlertTriangle, Layers, MessageSquare, ExternalLink, Award
} from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { API_URL, apiHeaders } from '../lib/api';
import { useAnalysisStore } from '../store/useAnalysisStore';

interface Insight {
  title: string;
  detail: string;
  impact_score: number;
  confidence: number;
  effect_size: string;
  practical_significance: string;
  supporting_chart?: string | null;
  category: string;
  section_title: string;
}

const CATEGORY_META: Record<string, { label: string; icon: React.ReactNode; color: string; bg: string }> = {
  findings_group: { label: 'Statistical', icon: <BarChart2 size={13} />, color: 'text-sky-400', bg: 'bg-sky-950/60 border-sky-800/40' },
  key_finding: { label: 'Key Finding', icon: <Star size={13} />, color: 'text-amber-400', bg: 'bg-amber-950/60 border-amber-800/40' },
  causal: { label: 'Causal', icon: <GitBranch size={13} />, color: 'text-violet-400', bg: 'bg-violet-950/60 border-violet-800/40' },
  ml: { label: 'ML / Predictive', icon: <Brain size={13} />, color: 'text-emerald-400', bg: 'bg-emerald-950/60 border-emerald-800/40' },
  cohort: { label: 'Cohort', icon: <Users size={13} />, color: 'text-cyan-400', bg: 'bg-cyan-950/60 border-cyan-800/40' },
  benchmark: { label: 'Benchmark', icon: <Award size={13} />, color: 'text-rose-400', bg: 'bg-rose-950/60 border-rose-800/40' },
  trend_analysis: { label: 'Trend', icon: <TrendingUp size={13} />, color: 'text-blue-400', bg: 'bg-blue-950/60 border-blue-800/40' },
  anomalies: { label: 'Anomaly', icon: <AlertTriangle size={13} />, color: 'text-orange-400', bg: 'bg-orange-950/60 border-orange-800/40' },
  recommendations: { label: 'Recommendation', icon: <Target size={13} />, color: 'text-green-400', bg: 'bg-green-950/60 border-green-800/40' },
};

const getCategoryMeta = (cat: string) => CATEGORY_META[cat] || { label: cat, icon: <Layers size={13} />, color: 'text-slate-400', bg: 'bg-slate-900/60 border-slate-700/40' };

const ImpactBar = ({ score }: { score: number }) => {
  const pct = (score / 10) * 100;
  const color = score >= 8 ? '#ef4444' : score >= 6 ? '#f59e0b' : '#38bdf8';
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 rounded-full bg-white/10 overflow-hidden">
        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-[11px] font-mono font-bold" style={{ color }}>{score}/10</span>
    </div>
  );
};

const ConfidenceRing = ({ confidence }: { confidence: number }) => {
  const r = 14; const circ = 2 * Math.PI * r;
  const fill = (confidence / 100) * circ;
  const color = confidence >= 80 ? '#22c55e' : confidence >= 60 ? '#f59e0b' : '#ef4444';
  return (
    <svg width="36" height="36" viewBox="0 0 36 36">
      <circle cx="18" cy="18" r={r} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="3" />
      <circle cx="18" cy="18" r={r} fill="none" stroke={color} strokeWidth="3"
        strokeDasharray={`${fill} ${circ}`} strokeLinecap="round"
        transform="rotate(-90 18 18)" style={{ transition: 'stroke-dasharray 0.8s ease' }} />
      <text x="18" y="22" textAnchor="middle" fontSize="8" fill={color} fontWeight="bold">{confidence}%</text>
    </svg>
  );
};

export function Insights() {
  const { id } = useParams<{ id?: string }>();
  const { currentReportId, currentReportData } = useAnalysisStore();
  const reportId = id || currentReportId;

  const [insights, setInsights] = useState<Insight[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [activeFilter, setActiveFilter] = useState<string>('all');
  const [sortBy, setSortBy] = useState<'impact' | 'confidence'>('impact');
  const [expanded, setExpanded] = useState<number | null>(null);

  const reportTitle = currentReportData?.report?.title || currentReportData?.filename || 'Report';

  useEffect(() => {
    if (!reportId) return;
    setLoading(true);
    fetch(`${API_URL}/api/reports/${reportId}/insights`, { headers: apiHeaders() })
      .then(r => r.json())
      .then(data => { setInsights(data.insights || []); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [reportId]);

  const categories = ['all', ...Array.from(new Set(insights.map(i => i.category)))];

  const filtered = insights
    .filter(i => activeFilter === 'all' || i.category === activeFilter)
    .filter(i => !search || i.title.toLowerCase().includes(search.toLowerCase()) || i.detail.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => sortBy === 'impact' ? b.impact_score - a.impact_score : b.confidence - a.confidence);

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100">
      {/* Header */}
      <div className="border-b border-white/5 bg-[#0A0F1E]/80 backdrop-blur-md sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
                <Link to={`/reports/${reportId}`} className="hover:text-sky-400 transition-colors">Report</Link>
                <ChevronRight size={12} />
                <span className="text-slate-300">Insights Feed</span>
              </div>
              <h1 className="text-xl font-bold text-white flex items-center gap-2">
                <Zap size={20} className="text-amber-400" />
                Insights Feed
                <span className="text-sm font-normal text-slate-400 ml-2">— {reportTitle}</span>
              </h1>
              <p className="text-xs text-slate-500 mt-0.5">All findings ranked by impact score · {filtered.length} insights</p>
            </div>
            <div className="flex items-center gap-2">
              <Link to={`/reports/${reportId}`}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-white/10 text-slate-400 hover:text-sky-400 hover:border-sky-800 transition-all">
                <ExternalLink size={12} /> Full Report
              </Link>
              <Link to={`/reports/${reportId}`} state={{ openChat: true }}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white transition-all">
                <MessageSquare size={12} /> Ask Analyst
              </Link>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-6">
        {/* Filters & Search Bar */}
        <div className="flex flex-col sm:flex-row gap-3 mb-6">
          {/* Search */}
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search insights..."
              className="w-full bg-white/5 border border-white/10 rounded-xl pl-9 pr-4 py-2.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-600/60 transition-all"
            />
          </div>

          {/* Sort */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Sort:</span>
            {(['impact', 'confidence'] as const).map(s => (
              <button key={s} onClick={() => setSortBy(s)}
                className={`text-xs px-3 py-1.5 rounded-lg border transition-all capitalize ${sortBy === s ? 'bg-sky-600 border-sky-500 text-white' : 'border-white/10 text-slate-400 hover:border-sky-800'}`}>
                {s}
              </button>
            ))}
          </div>
        </div>

        {/* Category Filters */}
        <div className="flex gap-2 flex-wrap mb-6">
          {categories.map(cat => {
            const meta = getCategoryMeta(cat);
            return (
              <button key={cat} onClick={() => setActiveFilter(cat)}
                className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border transition-all ${activeFilter === cat
                  ? `${meta.bg} ${meta.color} border-current`
                  : 'border-white/10 text-slate-400 hover:border-white/20'}`}>
                {cat !== 'all' && meta.icon}
                {cat === 'all' ? `All (${insights.length})` : `${meta.label} (${insights.filter(i => i.category === cat).length})`}
              </button>
            );
          })}
        </div>

        {/* Loading */}
        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="flex items-center gap-3 text-slate-400">
              <div className="w-5 h-5 border-2 border-sky-500/50 border-t-sky-500 rounded-full animate-spin" />
              Loading insights…
            </div>
          </div>
        )}

        {error && (
          <div className="bg-red-950/40 border border-red-800/40 rounded-xl p-4 text-red-400 text-sm">{error}</div>
        )}

        {/* Insights Grid */}
        <div className="space-y-3">
          <AnimatePresence>
            {filtered.map((insight, idx) => {
              const meta = getCategoryMeta(insight.category);
              const isOpen = expanded === idx;
              return (
                <motion.div
                  key={`${insight.title}-${idx}`}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ delay: idx * 0.03 }}
                  className={`rounded-xl border bg-gradient-to-r from-white/[0.03] to-transparent overflow-hidden cursor-pointer ${meta.bg} hover:border-opacity-60 transition-all`}
                  onClick={() => setExpanded(isOpen ? null : idx)}
                >
                  <div className="px-5 py-4">
                    <div className="flex items-start gap-4">
                      {/* Confidence ring */}
                      <div className="shrink-0 mt-0.5">
                        <ConfidenceRing confidence={insight.confidence} />
                      </div>

                      {/* Main content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                          <span className={`flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full border ${meta.bg} ${meta.color}`}>
                            {meta.icon} {meta.label}
                          </span>
                          {insight.section_title && insight.section_title !== meta.label && (
                            <span className="text-[11px] text-slate-500">{insight.section_title}</span>
                          )}
                        </div>

                        <h3 className="text-[15px] font-semibold text-white leading-snug mb-1.5">{insight.title}</h3>

                        <p className={`text-sm text-slate-400 leading-relaxed ${isOpen ? '' : 'line-clamp-2'}`}>
                          {insight.detail}
                        </p>

                        {isOpen && insight.practical_significance && (
                          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-3 p-3 rounded-lg bg-white/5 border border-white/10">
                            <p className="text-xs text-sky-400 font-semibold mb-1">💡 Practical Significance</p>
                            <p className="text-sm text-slate-300">{insight.practical_significance}</p>
                          </motion.div>
                        )}

                        {isOpen && insight.effect_size && (
                          <div className="mt-2 flex items-center gap-2">
                            <Activity size={12} className="text-slate-500" />
                            <span className="text-xs text-slate-400 font-mono">{insight.effect_size}</span>
                          </div>
                        )}
                      </div>

                      {/* Right side: impact + actions */}
                      <div className="shrink-0 flex flex-col items-end gap-2">
                        <ImpactBar score={insight.impact_score} />
                        <div className="flex items-center gap-1.5">
                          <Link
                            to={`/reports/${reportId}`}
                            state={{ scrollToFinding: insight.title }}
                            onClick={e => e.stopPropagation()}
                            className={`text-[11px] px-2 py-1 rounded-md border border-white/10 ${meta.color} hover:bg-white/5 transition-all flex items-center gap-1`}>
                            <ExternalLink size={10} /> View
                          </Link>
                          <Link
                            to={`/reports/${reportId}`}
                            state={{ openChat: true, chatPrefill: `Tell me more about: ${insight.title}` }}
                            onClick={e => e.stopPropagation()}
                            className="text-[11px] px-2 py-1 rounded-md bg-sky-900/40 border border-sky-800/40 text-sky-400 hover:bg-sky-900/60 transition-all flex items-center gap-1">
                            <MessageSquare size={10} /> Ask
                          </Link>
                        </div>
                      </div>
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>

          {!loading && filtered.length === 0 && (
            <div className="text-center py-20 text-slate-500">
              <Zap size={32} className="mx-auto mb-3 opacity-30" />
              <p>No insights match your filters.</p>
              <button onClick={() => { setSearch(''); setActiveFilter('all'); }} className="mt-2 text-sky-400 text-sm hover:underline">
                Clear filters
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
