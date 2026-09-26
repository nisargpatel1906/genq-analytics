import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  TrendingUp, Brain, GitBranch, Users, Zap, BarChart2,
  Activity, Search, ChevronRight, Star, Target,
  AlertTriangle, Layers, MessageSquare, ExternalLink, Award
} from 'lucide-react';
import { Logo } from '../components/ui/Logo';
import { Link, useParams } from 'react-router-dom';
import { API_URL, apiHeaders } from '../lib/api';
import { useAnalysisStore } from '../store/useAnalysisStore';
import { Button } from '../components/ui/Button';

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
  findings_group: { label: 'Statistical', icon: <BarChart2 size={13} />, color: 'text-accent', bg: 'bg-surface-secondary border-border' },
  key_finding: { label: 'Key Finding', icon: <Star size={13} />, color: 'text-warning', bg: 'bg-warning/10 border-warning/30' },
  causal: { label: 'Causal', icon: <GitBranch size={13} />, color: 'text-accent', bg: 'bg-surface-secondary border-accent/30' },
  ml: { label: 'Predictive ML', icon: <Brain size={13} />, color: 'text-success', bg: 'bg-success/15 border-success/30' },
  cohort: { label: 'Cohort Segment', icon: <Users size={13} />, color: 'text-info', bg: 'bg-surface-secondary border-border' },
  benchmark: { label: 'Benchmark', icon: <Award size={13} />, color: 'text-accent', bg: 'bg-surface-secondary border-border' },
  trend_analysis: { label: 'Temporal Trend', icon: <TrendingUp size={13} />, color: 'text-accent', bg: 'bg-surface-secondary border-border' },
  anomalies: { label: 'Anomaly', icon: <AlertTriangle size={13} />, color: 'text-warning', bg: 'bg-warning/15 border-warning/30' },
  recommendations: { label: 'Strategic Directive', icon: <Target size={13} />, color: 'text-success', bg: 'bg-success/15 border-success/30' },
};

const getCategoryMeta = (cat: string) =>
  CATEGORY_META[cat] || {
    label: cat,
    icon: <Layers size={13} />,
    color: 'text-muted',
    bg: 'bg-surface-secondary border-border',
  };

const ImpactBar = ({ score }: { score: number }) => {
  const pct = (score / 10) * 100;
  const color = score >= 8 ? '#8B3A3A' : score >= 6 ? '#B8860B' : '#8B6F3E';
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 rounded-full bg-surface-secondary border border-border overflow-hidden">
        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-[11px] font-mono font-bold" style={{ color }}>{score}/10</span>
    </div>
  );
};

const ConfidenceRing = ({ confidence }: { confidence: number }) => {
  const r = 14;
  const circ = 2 * Math.PI * r;
  const fill = (confidence / 100) * circ;
  const color = confidence >= 80 ? '#5C6E3E' : confidence >= 60 ? '#B8860B' : '#8B3A3A';
  return (
    <svg width="36" height="36" viewBox="0 0 36 36">
      <circle cx="18" cy="18" r={r} fill="none" stroke="#D4C9B0" strokeWidth="2.5" />
      <circle
        cx="18"
        cy="18"
        r={r}
        fill="none"
        stroke={color}
        strokeWidth="2.5"
        strokeDasharray={`${fill} ${circ}`}
        strokeLinecap="round"
        transform="rotate(-90 18 18)"
        style={{ transition: 'stroke-dasharray 0.8s ease' }}
      />
      <text x="18" y="21.5" textAnchor="middle" fontSize="8" fill={color} fontWeight="bold" fontFamily="var(--font-mono)">
        {confidence}%
      </text>
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

  const reportTitle = currentReportData?.report?.title || currentReportData?.filename || 'Autonomous Report';

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
    <div className="min-h-screen bg-bg text-fg font-body">
      {/* Header */}
      <div className="border-b border-border bg-surface/90 backdrop-blur-md sticky top-0 z-20 shadow-custom-sm">
        <div className="max-w-6xl mx-auto px-6 py-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-xs text-muted mb-1">
                <Link to={`/reports/${reportId}`} className="hover:text-accent transition-colors font-medium">Synthesis Report</Link>
                <ChevronRight size={12} />
                <span className="text-fg font-medium">Insights Feed</span>
              </div>
              <h1 className="font-heading text-2xl font-bold text-fg flex items-center gap-2.5">
                <Zap size={20} className="text-accent" />
                Empirical Insights Feed
                <span className="text-sm font-normal font-body text-muted ml-2">— {reportTitle}</span>
              </h1>
              <p className="font-body text-xs text-muted mt-1">Autonomous findings ranked by empirical impact and verification score · {filtered.length} insights</p>
            </div>
            <div className="flex items-center gap-2.5">
              <Link to={`/reports/${reportId}`}>
                <Button variant="outlined" size="sm" className="gap-1.5">
                  <ExternalLink size={12} /> Full Report
                </Button>
              </Link>
              <Link to={`/reports/${reportId}`} state={{ openChat: true }}>
                <Button variant="primary" size="sm" className="gap-1.5">
                  <MessageSquare size={12} /> Ask Analyst
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Filters & Search Bar */}
        <div className="flex flex-col sm:flex-row gap-3 mb-6">
          {/* Search */}
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search empirical findings and hypotheses..."
              className="w-full bg-surface border border-border rounded-[8px] pl-9 pr-4 py-2 text-sm text-fg placeholder:text-muted focus:outline-none focus:border-accent transition-all shadow-custom-sm"
            />
          </div>

          {/* Sort */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted font-medium">Sort by:</span>
            {(['impact', 'confidence'] as const).map(s => (
              <button
                key={s}
                onClick={() => setSortBy(s)}
                className={`text-xs px-3 py-1.5 rounded-[6px] border transition-all capitalize font-medium ${
                  sortBy === s
                    ? 'bg-accent border-accent text-[#FDFAF5] shadow-custom-sm'
                    : 'bg-surface border-border text-muted hover:text-fg hover:border-accent/40'
                }`}
              >
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
              <button
                key={cat}
                onClick={() => setActiveFilter(cat)}
                className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-[6px] border transition-all font-medium ${
                  activeFilter === cat
                    ? 'bg-surface-secondary text-accent border-accent font-semibold shadow-custom-sm'
                    : 'bg-surface border-border text-muted hover:text-fg hover:border-border/80'
                }`}
              >
                {cat !== 'all' && meta.icon}
                {cat === 'all' ? `All Findings (${insights.length})` : `${meta.label} (${insights.filter(i => i.category === cat).length})`}
              </button>
            );
          })}
        </div>

        {/* Loading */}
        {loading && (
          <div className="flex items-center justify-center py-24">
            <div className="flex items-center gap-3 text-muted">
              <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
              Synthesizing findings catalog…
            </div>
          </div>
        )}

        {error && (
          <div className="bg-error/10 border border-error/30 rounded-[8px] p-4 text-error text-sm font-medium mb-6">
            {error}
          </div>
        )}

        {/* Insights Grid */}
        <div className="space-y-3.5">
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
                  transition={{ delay: idx * 0.025 }}
                  className={`rounded-[12px] border bg-surface overflow-hidden cursor-pointer transition-all shadow-custom-sm hover:shadow-custom-md ${
                    isOpen ? 'border-accent ring-1 ring-accent/30' : 'border-border hover:border-accent/40'
                  }`}
                  onClick={() => setExpanded(isOpen ? null : idx)}
                >
                  <div className="px-6 py-4">
                    <div className="flex items-start gap-4">
                      {/* Confidence ring */}
                      <div className="shrink-0 mt-0.5">
                        <ConfidenceRing confidence={insight.confidence} />
                      </div>

                      {/* Main content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                          <span className={`flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.08em] px-2 py-0.5 rounded-[4px] border ${meta.bg} ${meta.color}`}>
                            {meta.icon} {meta.label}
                          </span>
                          {insight.section_title && insight.section_title !== meta.label && (
                            <span className="text-[11px] text-muted font-medium">{insight.section_title}</span>
                          )}
                        </div>

                        <h3 className="font-heading text-[16px] font-semibold text-fg leading-snug mb-1.5">
                          {insight.title}
                        </h3>

                        <p className={`font-body text-[13px] text-muted leading-relaxed ${isOpen ? '' : 'line-clamp-2'}`}>
                          {insight.detail}
                        </p>

                        {isOpen && insight.practical_significance && (
                          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-3.5 p-3.5 rounded-[8px] bg-surface-secondary/50 border border-border">
                            <p className="font-body text-xs text-accent font-semibold mb-1 flex items-center gap-1.5">
                              <Logo size={12} className="text-accent" /> Strategic Significance
                            </p>
                            <p className="font-body text-[13px] text-fg leading-relaxed">{insight.practical_significance}</p>
                          </motion.div>
                        )}

                        {isOpen && insight.effect_size && (
                          <div className="mt-2.5 flex items-center gap-2">
                            <Activity size={12} className="text-muted" />
                            <span className="text-xs text-muted font-mono">{insight.effect_size}</span>
                          </div>
                        )}
                      </div>

                      {/* Right side: impact + actions */}
                      <div className="shrink-0 flex flex-col items-end gap-2.5">
                        <ImpactBar score={insight.impact_score} />
                        <div className="flex items-center gap-1.5">
                          <Link
                            to={`/reports/${reportId}`}
                            state={{ scrollToFinding: insight.title }}
                            onClick={e => e.stopPropagation()}
                            className="text-[11px] font-body font-medium px-2.5 py-1 rounded-[6px] border border-border text-fg hover:border-accent hover:text-accent transition-all flex items-center gap-1 bg-surface"
                          >
                            <ExternalLink size={10} /> View
                          </Link>
                          <Link
                            to={`/reports/${reportId}`}
                            state={{ openChat: true, chatPrefill: `Provide strategic deep-dive regarding: ${insight.title}` }}
                            onClick={e => e.stopPropagation()}
                            className="text-[11px] font-body font-medium px-2.5 py-1 rounded-[6px] bg-surface-secondary border border-border text-accent hover:border-accent transition-all flex items-center gap-1"
                          >
                            <MessageSquare size={10} /> Inquire
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
            <div className="text-center py-20 text-muted bg-surface rounded-[12px] border border-border shadow-custom-sm">
              <Zap size={32} className="mx-auto mb-3 opacity-30 text-accent" />
              <p className="font-heading text-lg font-medium text-fg">No findings match your filters</p>
              <button onClick={() => { setSearch(''); setActiveFilter('all'); }} className="mt-2 text-accent text-sm hover:underline font-body">
                Reset filters
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
