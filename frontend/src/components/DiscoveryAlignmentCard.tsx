import { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  TrendingUp,
  Brain,
  GitBranch,
  ShieldAlert,
  Award,
  Layers,
  BarChart2,
  ArrowRight,
  Flame,
  Check,
  X,
  Zap,
  Star
} from 'lucide-react';
import { Logo } from './ui/Logo';
import { Button } from './ui/Button';
import {
  useAnalysisStore,
  type DiscoveryProfile
} from '../store/useAnalysisStore';

interface DiscoveryAlignmentCardProps {
  jobId: string;
  profile: DiscoveryProfile;
  onLaunch: () => void;
  onCancel: () => void;
}

export function DiscoveryAlignmentCard({
  jobId,
  profile,
  onLaunch,
  onCancel
}: DiscoveryAlignmentCardProps) {
  const { alignJob } = useAnalysisStore();

  // Initialize selected answers with defaults from questions
  const [answers, setAnswers] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const q of profile.questions || []) {
      initial[q.id] = q.default || (q.options && q.options[0]) || '';
    }
    return initial;
  });

  // Track custom input text per question
  const [customInputs, setCustomInputs] = useState<Record<string, string>>({});

  // Initialize selected modules with viable modules by default
  const [selectedModules, setSelectedModules] = useState<string[]>(() => {
    return (profile.viable_modules || [])
      .filter((m) => m.viable)
      .map((m) => m.id);
  });

  const [isSubmitting, setIsSubmitting] = useState(false);

  // Toggle module selection
  const handleToggleModule = (moduleId: string, viable: boolean) => {
    if (!viable) return;
    setSelectedModules((prev) =>
      prev.includes(moduleId)
        ? prev.filter((id) => id !== moduleId)
        : [...prev, moduleId]
    );
  };

  // Select an option chip
  const handleSelectOption = (questionId: string, option: string) => {
    setAnswers((prev) => ({ ...prev, [questionId]: option }));
    // Clear custom input if an option chip is chosen
    setCustomInputs((prev) => ({ ...prev, [questionId]: '' }));
  };

  // Handle custom input change
  const handleCustomChange = (questionId: string, text: string) => {
    setCustomInputs((prev) => ({ ...prev, [questionId]: text }));
    if (text.trim()) {
      setAnswers((prev) => ({ ...prev, [questionId]: text.trim() }));
    }
  };

  // Calculate dynamic savings
  const totalSeniorModules = profile.viable_modules?.length || 7;
  const selectedCount = selectedModules.length;
  const unselectedCount = totalSeniorModules - selectedCount;
  
  const estimatedSavingsPct = useMemo(() => {
    let totalSavings = 0;
    for (const m of profile.viable_modules || []) {
      if (!selectedModules.includes(m.id)) {
        totalSavings += m.token_savings_pct || 15;
      }
    }
    return Math.min(Math.round(totalSavings), 75);
  }, [profile.viable_modules, selectedModules]);

  // Launch aligned job
  const handleLaunchAligned = async () => {
    setIsSubmitting(true);
    try {
      await alignJob(jobId, answers, selectedModules, false);
      onLaunch();
    } catch {
      setIsSubmitting(false);
    }
  };

  // Quick auto-analyze (all viable)
  const handleQuickAuto = async () => {
    setIsSubmitting(true);
    try {
      await alignJob(jobId, answers, selectedModules, true);
      onLaunch();
    } catch {
      setIsSubmitting(false);
    }
  };

  // Module Icon Helper
  const getModuleIcon = (id: string) => {
    const iconClass = "w-4 h-4 text-accent stroke-[1.75]";
    switch (id) {
      case 'forecaster':
        return <TrendingUp className={iconClass} />;
      case 'cohort_analyst':
        return <Layers className={iconClass} />;
      case 'experimentation':
        return <Flame className={iconClass} />;
      case 'ml_modeler':
        return <Brain className={iconClass} />;
      case 'causal_analyst':
        return <GitBranch className={iconClass} />;
      case 'anomaly_detector':
        return <ShieldAlert className={iconClass} />;
      case 'benchmarking':
        return <Award className={iconClass} />;
      default:
        return <BarChart2 className={iconClass} />;
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -15 }}
      className="w-full bg-surface border border-border rounded-[12px] overflow-hidden shadow-custom-md text-fg"
    >
      {/* ── Top Header Banner ── */}
      <div className="p-6 md:p-8 border-b border-border bg-gradient-to-r from-surface-secondary/80 to-surface">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-3">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="w-2.5 h-2.5 rounded-full bg-accent animate-pulse" />
            <span className="font-mono text-[11px] tracking-wider uppercase font-semibold text-accent bg-surface-secondary px-2.5 py-1 rounded-[4px] border border-border">
              {profile.domain} ({profile.domain_confidence}% Match)
            </span>
            <span className="font-mono text-[11px] text-muted bg-surface-secondary/60 px-2 py-0.5 rounded-[4px] border border-border/60">
              {profile.dataset_summary}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] text-accent bg-surface-secondary px-2.5 py-1 rounded-[6px] border border-accent/30 font-semibold flex items-center gap-1.5">
              <Logo size={14} className="text-accent" />
              {unselectedCount > 0 ? `-${estimatedSavingsPct}% Compute Optimized` : 'Full Spectrum Suite'}
            </span>
          </div>
        </div>

        <h2 className="font-heading text-[26px] md:text-[30px] font-bold text-fg leading-tight">
          Business Discovery &amp; Strategic Alignment
        </h2>
        <p className="font-body text-[14px] text-muted mt-2 max-w-[720px] leading-relaxed">
          {profile.domain_description} To guarantee rigorous analytical precision and optimize execution efficiency, tailor your business context and select specific quantitative modules.
        </p>
      </div>

      <div className="p-6 md:p-8 space-y-8">
        {/* ── Section 1: Dynamic Discovery Q&A ── */}
        <div>
          <div className="flex items-center gap-2 mb-4">
            <div className="w-6 h-6 rounded-full bg-surface-secondary border border-border flex items-center justify-center text-accent font-mono text-[12px] font-bold">
              1
            </div>
            <h3 className="font-heading text-[18px] font-bold text-fg">
              Business Alignment Questions
            </h3>
            <span className="font-body text-[12px] text-muted ml-2">
              (Directs autonomous hypothesis formulation &amp; peer debate)
            </span>
          </div>

          <div className="space-y-5">
            {(profile.questions || []).map((q) => {
              const currentVal = answers[q.id] || '';
              const isCustom = customInputs[q.id] !== undefined && customInputs[q.id] !== '';

              return (
                <div
                  key={q.id}
                  className="p-5 rounded-[10px] bg-surface-secondary/30 border border-border transition-all hover:border-accent/50"
                >
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <div>
                      <span className="font-body text-[10px] tracking-wider uppercase font-semibold text-accent bg-surface-secondary px-2 py-0.5 rounded-[4px] border border-border mr-2">
                        {q.category}
                      </span>
                      <span className="font-heading text-[16px] font-semibold text-fg">
                        {q.title}
                      </span>
                    </div>
                  </div>

                  <p className="font-body text-[13px] text-muted mb-3 leading-relaxed">
                    {q.description}
                  </p>

                  {/* Option Chips */}
                  <div className="flex flex-wrap gap-2 mb-3">
                    {(q.options || []).map((opt) => {
                      const isSelected = !isCustom && currentVal === opt;
                      return (
                        <button
                          key={opt}
                          type="button"
                          onClick={() => handleSelectOption(q.id, opt)}
                          className={`text-left font-body text-[13px] px-3.5 py-2 rounded-[8px] transition-all duration-150 border ${
                            isSelected
                              ? 'bg-accent text-[#FDFAF5] border-accent font-semibold shadow-custom-sm'
                              : 'bg-surface text-fg border-border hover:bg-surface-secondary hover:border-accent/40'
                          }`}
                        >
                          <span className="flex items-center gap-1.5">
                            {isSelected && <Check className="w-3.5 h-3.5 stroke-[2.5]" />}
                            {opt}
                          </span>
                        </button>
                      );
                    })}
                  </div>

                  {/* Custom Write-in Field */}
                  {q.allow_custom && (
                    <div className="mt-2">
                      <input
                        type="text"
                        value={customInputs[q.id] || ''}
                        onChange={(e) => handleCustomChange(q.id, e.target.value)}
                        placeholder={q.custom_placeholder || 'Or write custom business nuance...'}
                        className="w-full bg-surface border border-border focus:border-accent focus:ring-1 focus:ring-accent rounded-[8px] px-3.5 py-2 font-body text-[13px] text-fg placeholder:text-muted/60 outline-none transition-all"
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* ── Section 2: Selective Module Execution ── */}
        <div>
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-full bg-surface-secondary border border-border flex items-center justify-center text-accent font-mono text-[12px] font-bold">
                2
              </div>
              <h3 className="font-heading text-[18px] font-bold text-fg">
                Selective Analysis Modules
              </h3>
              <span className="font-body text-[12px] text-muted ml-2">
                (Adaptive execution: bypass irrelevant agents to streamline processing)
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span className="font-mono text-[11px] text-fg font-medium bg-surface-secondary px-3 py-1 rounded-[6px] border border-border">
                {selectedCount} of {totalSeniorModules} Modules Selected
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
            {(profile.viable_modules || []).map((m) => {
              const isSelected = selectedModules.includes(m.id);
              const isViable = m.viable;

              return (
                <div
                  key={m.id}
                  onClick={() => handleToggleModule(m.id, isViable)}
                  className={`p-4 rounded-[10px] border transition-all select-none ${
                    !isViable
                      ? 'bg-surface-secondary/20 border-border/50 opacity-50 cursor-not-allowed'
                      : isSelected
                      ? 'bg-surface border-accent shadow-custom-sm cursor-pointer hover:border-accent'
                      : 'bg-surface-secondary/30 border-border cursor-pointer hover:bg-surface-secondary/50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3">
                      <div
                        className={`w-5 h-5 rounded-[5px] mt-0.5 border flex items-center justify-center transition-all ${
                          !isViable
                            ? 'border-border bg-surface-secondary/50'
                            : isSelected
                            ? 'border-accent bg-accent text-[#FDFAF5]'
                            : 'border-border bg-surface'
                        }`}
                      >
                        {isSelected && isViable && <Check className="w-3.5 h-3.5 stroke-[2.5]" />}
                        {!isViable && <X className="w-3 h-3 text-error" />}
                      </div>

                      <div>
                        <div className="flex items-center gap-2">
                          {getModuleIcon(m.id)}
                          <span className={`font-heading text-[15px] font-bold ${isViable ? 'text-fg' : 'text-muted'}`}>
                            {m.name}
                          </span>
                        </div>
                        <p className="font-body text-[12px] text-muted mt-1 leading-snug">
                          {m.role || m.description}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-col items-end gap-1 flex-shrink-0">
                      {isViable ? (
                        <>
                          {m.recommended && (
                            <span className="font-body text-[10px] uppercase font-semibold text-accent bg-surface-secondary px-2 py-0.5 rounded-[4px] border border-accent/30 flex items-center gap-1">
                              <Star className="w-2.5 h-2.5 fill-accent" /> Recommended
                            </span>
                          )}
                          {!isSelected && (
                            <span className="font-mono text-[10px] text-success font-semibold bg-success/15 px-2 py-0.5 rounded-[4px] border border-success/30">
                              Save ~{m.token_savings_pct}%
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="font-body text-[10px] font-semibold text-error bg-error/15 px-2 py-0.5 rounded-[4px] border border-error/30">
                          Unavailable: {m.reason}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ── Footer Actions ── */}
        <div className="pt-5 border-t border-border flex flex-wrap items-center justify-between gap-4">
          <button
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
            className="font-body text-[13px] text-muted hover:text-fg transition-colors"
          >
            &larr; Cancel &amp; Deposit Different Dataset
          </button>

          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="outlined"
              size="md"
              onClick={handleQuickAuto}
              disabled={isSubmitting}
              className="gap-2"
            >
              <Zap className="w-3.5 h-3.5 text-accent" /> Quick Synthesis (All Viable)
            </Button>

            <Button
              variant="primary"
              size="md"
              onClick={handleLaunchAligned}
              disabled={isSubmitting || selectedModules.length === 0}
              className="gap-2"
            >
              {isSubmitting ? (
                <>
                  <div className="w-4 h-4 border-2 border-[#FDFAF5] border-t-transparent rounded-full animate-spin" />
                  <span>Initiating Pipeline...</span>
                </>
              ) : (
                <>
                  <span>Initiate Aligned Synthesis</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
