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
  X
} from 'lucide-react';
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
    } catch (e) {
      setIsSubmitting(false);
    }
  };

  // Quick auto-analyze (all viable)
  const handleQuickAuto = async () => {
    setIsSubmitting(true);
    try {
      await alignJob(jobId, answers, selectedModules, true);
      onLaunch();
    } catch (e) {
      setIsSubmitting(false);
    }
  };

  // Module Icon Helper
  const getModuleIcon = (id: string) => {
    switch (id) {
      case 'forecaster':
        return <TrendingUp className="w-4 h-4 text-[#8B6F3E]" />;
      case 'cohort_analyst':
        return <Layers className="w-4 h-4 text-[#8B6F3E]" />;
      case 'experimentation':
        return <Flame className="w-4 h-4 text-[#8B6F3E]" />;
      case 'ml_modeler':
        return <Brain className="w-4 h-4 text-[#8B6F3E]" />;
      case 'causal_analyst':
        return <GitBranch className="w-4 h-4 text-[#8B6F3E]" />;
      case 'anomaly_detector':
        return <ShieldAlert className="w-4 h-4 text-[#8B6F3E]" />;
      case 'benchmarking':
        return <Award className="w-4 h-4 text-[#8B6F3E]" />;
      default:
        return <BarChart2 className="w-4 h-4 text-[#8B6F3E]" />;
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -15 }}
      className="w-full bg-[#FAF7F2] border border-[#D4C9B0] rounded-[16px] overflow-hidden shadow-md text-[#1A1208]"
    >
      {/* ── Top Header Banner ── */}
      <div className="p-6 md:p-8 border-b border-[#D4C9B0] bg-gradient-to-r from-[#EDE4D0]/90 to-[#FAF7F2]">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-3">
          <div className="flex items-center gap-2.5">
            <span className="w-2.5 h-2.5 rounded-full bg-[#8B6F3E] animate-pulse" />
            <span className="font-mono text-[11px] tracking-wider uppercase font-semibold text-[#8B6F3E] bg-[#EDE4D0] px-2.5 py-1 rounded border border-[#D4C9B0]">
              {profile.domain} ({profile.domain_confidence}% Match)
            </span>
            <span className="font-mono text-[11px] text-[#6B5B4E] bg-[#EDE4D0]/60 px-2 py-0.5 rounded border border-[#D4C9B0]/60">
              {profile.dataset_summary}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] text-[#8B6F3E] bg-[#EDE4D0] px-2.5 py-1 rounded border border-[#8B6F3E]/40 font-medium">
              🌿 {unselectedCount > 0 ? `-${estimatedSavingsPct}% Tokens & Compute Saved` : 'Full Spectrum Suite'}
            </span>
          </div>
        </div>

        <h2 className="font-serif text-[26px] md:text-[30px] font-bold text-[#1A1208] leading-tight">
          Business Discovery & Strategic Alignment
        </h2>
        <p className="font-mono text-[13px] text-[#6B5B4E] mt-1.5 max-w-[700px] leading-relaxed">
          {profile.domain_description} To ensure maximum precision and avoid running unnecessary models, align your business context and select only the modules your problem statement requires.
        </p>
      </div>

      <div className="p-6 md:p-8 space-y-8">
        {/* ── Section 1: Dynamic Discovery Q&A ── */}
        <div>
          <div className="flex items-center gap-2 mb-4">
            <div className="w-6 h-6 rounded-full bg-[#8B6F3E]/10 border border-[#8B6F3E]/30 flex items-center justify-center text-[#8B6F3E] font-mono text-[12px] font-bold">
              1
            </div>
            <h3 className="font-serif text-[18px] font-bold text-[#1A1208]">
              Business Alignment Questions
            </h3>
            <span className="font-mono text-[11px] text-[#6B5B4E] ml-2">
              (Directs autonomous hypothesis formulation & peer debate)
            </span>
          </div>

          <div className="space-y-6">
            {(profile.questions || []).map((q) => {
              const currentVal = answers[q.id] || '';
              const isCustom = customInputs[q.id] !== undefined && customInputs[q.id] !== '';

              return (
                <div
                  key={q.id}
                  className="p-5 rounded-[12px] bg-[#EDE4D0]/30 border border-[#D4C9B0] transition-all hover:border-[#8B6F3E]/50"
                >
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <div>
                      <span className="font-mono text-[10px] tracking-wider uppercase font-semibold text-[#8B6F3E] bg-[#EDE4D0] px-2 py-0.5 rounded border border-[#D4C9B0] mr-2">
                        {q.category}
                      </span>
                      <span className="font-serif text-[15px] font-bold text-[#1A1208]">
                        {q.title}
                      </span>
                    </div>
                  </div>

                  <p className="font-mono text-[12px] text-[#6B5B4E] mb-3">
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
                          className={`text-left font-mono text-[12px] px-3.5 py-2 rounded-[8px] transition-all duration-150 border ${
                            isSelected
                              ? 'bg-[#8B6F3E] text-[#F5F0E8] border-[#8B6F3E] font-medium shadow-sm'
                              : 'bg-[#FAF7F2] text-[#1A1208] border-[#D4C9B0] hover:bg-[#EDE4D0] hover:border-[#8B6F3E]/40'
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
                        className="w-full bg-[#FAF7F2] border border-[#D4C9B0] focus:border-[#8B6F3E] focus:ring-1 focus:ring-[#8B6F3E] rounded-[8px] px-3.5 py-2 font-mono text-[12px] text-[#1A1208] placeholder:text-[#6B5B4E]/60 outline-none transition-all"
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
              <div className="w-6 h-6 rounded-full bg-[#8B6F3E]/10 border border-[#8B6F3E]/30 flex items-center justify-center text-[#8B6F3E] font-mono text-[12px] font-bold">
                2
              </div>
              <h3 className="font-serif text-[18px] font-bold text-[#1A1208]">
                Selective Analysis Modules
              </h3>
              <span className="font-mono text-[11px] text-[#6B5B4E] ml-2">
                (Adaptive execution: bypass irrelevant agents to save compute)
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span className="font-mono text-[12px] text-[#1A1208] font-medium bg-[#EDE4D0] px-3 py-1 rounded-full border border-[#D4C9B0]">
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
                  className={`p-4 rounded-[12px] border transition-all select-none ${
                    !isViable
                      ? 'bg-[#EDE4D0]/20 border-[#D4C9B0]/50 opacity-60 cursor-not-allowed'
                      : isSelected
                      ? 'bg-[#FAF7F2] border-[#8B6F3E] shadow-sm cursor-pointer hover:border-[#8B6F3E]'
                      : 'bg-[#EDE4D0]/30 border-[#D4C9B0] cursor-pointer hover:bg-[#EDE4D0]/50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3">
                      <div
                        className={`w-5 h-5 rounded-[5px] mt-0.5 border flex items-center justify-center transition-all ${
                          !isViable
                            ? 'border-[#D4C9B0] bg-[#EDE4D0]/50'
                            : isSelected
                            ? 'border-[#8B6F3E] bg-[#8B6F3E] text-[#F5F0E8]'
                            : 'border-[#D4C9B0] bg-[#FAF7F2]'
                        }`}
                      >
                        {isSelected && isViable && <Check className="w-3.5 h-3.5 stroke-[2.5]" />}
                        {!isViable && <X className="w-3 h-3 text-[#A23B2A]" />}
                      </div>

                      <div>
                        <div className="flex items-center gap-2">
                          {getModuleIcon(m.id)}
                          <span className={`font-serif text-[14px] font-bold ${isViable ? 'text-[#1A1208]' : 'text-[#6B5B4E]'}`}>
                            {m.name}
                          </span>
                        </div>
                        <p className="font-mono text-[11px] text-[#6B5B4E] mt-1 leading-snug">
                          {m.role || m.description}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-col items-end gap-1 flex-shrink-0">
                      {isViable ? (
                        <>
                          {m.recommended && (
                            <span className="font-mono text-[10px] uppercase font-bold text-[#8B6F3E] bg-[#EDE4D0] px-2 py-0.5 rounded border border-[#8B6F3E]/30">
                              ⭐ Recommended
                            </span>
                          )}
                          {!isSelected && (
                            <span className="font-mono text-[10px] text-[#2D5A43] font-semibold bg-[#2D5A43]/10 px-2 py-0.5 rounded border border-[#2D5A43]/20">
                              Save ~{m.token_savings_pct}%
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="font-mono text-[10px] font-semibold text-[#A23B2A] bg-[#A23B2A]/10 px-2 py-0.5 rounded border border-[#A23B2A]/20">
                          Not Viable: {m.reason}
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
        <div className="pt-4 border-t border-[#D4C9B0] flex flex-wrap items-center justify-between gap-4">
          <button
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
            className="font-mono text-[13px] text-[#6B5B4E] hover:text-[#1A1208] transition-colors"
          >
            ← Cancel & Upload Different File
          </button>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleQuickAuto}
              disabled={isSubmitting}
              className="px-4 py-2.5 rounded-[8px] border border-[#D4C9B0] bg-[#FAF7F2] hover:bg-[#EDE4D0] font-mono text-[13px] text-[#1A1208] font-medium transition-all"
            >
              ⚡ Quick Auto-Analyze (All Viable)
            </button>

            <Button
              onClick={handleLaunchAligned}
              disabled={isSubmitting || selectedModules.length === 0}
              className="px-6 py-2.5 bg-[#8B6F3E] hover:bg-[#725a31] text-[#F5F0E8] font-mono text-[13px] font-semibold rounded-[8px] shadow-sm flex items-center gap-2 transition-all"
            >
              {isSubmitting ? (
                <>
                  <div className="w-4 h-4 border-2 border-[#F5F0E8] border-t-transparent rounded-full animate-spin" />
                  <span>Launching Pipeline...</span>
                </>
              ) : (
                <>
                  <span>Launch Aligned Analysis</span>
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
