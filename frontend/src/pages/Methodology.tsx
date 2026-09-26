import { motion } from 'framer-motion';
import { Shield, Database, Brain, BarChart } from 'lucide-react';
import { Logo } from '../components/ui/Logo';

export function Methodology() {
  return (
    <div className="max-w-[840px] mx-auto py-20 px-6 font-body text-fg">
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        className="space-y-12"
      >
        <section className="space-y-3 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-[6px] bg-surface-secondary border border-border shadow-custom-sm mb-2">
            <Logo size={14} className="text-accent" />
            <span className="font-mono text-[10px] uppercase font-bold tracking-[0.12em] text-accent">
              Academic Intelligence Standard
            </span>
          </div>
          <h1 className="font-heading text-[42px] md:text-[48px] font-bold tracking-tight text-fg">
            Quantitative Methodology
          </h1>
          <p className="text-muted text-[17px] max-w-[560px] mx-auto leading-relaxed">
            The empirical principles and statistical rigor powering autonomous multi-agent synthesis.
          </p>
        </section>

        <section className="space-y-6">
          <div className="flex gap-5 p-6 bg-surface rounded-[12px] border border-border shadow-custom-sm">
            <div className="shrink-0 w-12 h-12 rounded-[8px] bg-surface-secondary border border-border flex items-center justify-center text-accent">
              <Database className="w-6 h-6" />
            </div>
            <div className="space-y-2">
              <h3 className="font-heading text-[20px] font-semibold text-fg">1. Ingestion, Sanitization &amp; Schema Profiling</h3>
              <p className="font-body text-[14px] leading-relaxed text-muted">
                GenQ Analytics accepts standard CSV and XLSX formats. Upon deposit, our engine conducts deterministic sanitization, handling missing values, casing standardizations, timestamp chronologies, and statistical distribution baselines to ensure mathematical integrity.
              </p>
            </div>
          </div>

          <div className="flex gap-5 p-6 bg-surface rounded-[12px] border border-border shadow-custom-sm">
            <div className="shrink-0 w-12 h-12 rounded-[8px] bg-surface-secondary border border-border flex items-center justify-center text-accent">
              <BarChart className="w-6 h-6" />
            </div>
            <div className="space-y-2">
              <h3 className="font-heading text-[20px] font-semibold text-fg">2. Empirical Hypothesis Formulation &amp; Multi-Variate Analysis</h3>
              <p className="font-body text-[14px] leading-relaxed text-muted">
                We orchestrate a multi-agent peer review loop. The Research Planner formulates quantitative null hypotheses, verified by the Data Scientist agent through effect sizes, confidence intervals, parametric tests, and outlier isolation (IQR/Z-score), rejecting false signals.
              </p>
            </div>
          </div>

          <div className="flex gap-5 p-6 bg-surface rounded-[12px] border border-border shadow-custom-sm">
            <div className="shrink-0 w-12 h-12 rounded-[8px] bg-surface-secondary border border-border flex items-center justify-center text-accent">
              <Brain className="w-6 h-6" />
            </div>
            <div className="space-y-2">
              <h3 className="font-heading text-[20px] font-semibold text-fg">3. Autonomous Synthesis &amp; Executive Directives</h3>
              <p className="font-body text-[14px] leading-relaxed text-muted">
                The synthesized mathematical profile is scrutinized by the Reflector and Strategic Insights agents. Rather than superficial summaries, the agents act as an elite senior quantitative consultancy, producing executive directives, causal distinctions, and actionable strategies.
              </p>
            </div>
          </div>
        </section>

        <section className="p-8 bg-surface rounded-[12px] border border-border space-y-4 shadow-custom-sm">
          <div className="flex items-center gap-2 text-accent">
            <Shield className="w-5 h-5 text-accent" />
            <span className="font-mono font-bold text-[11px] uppercase tracking-widest text-accent">Privacy &amp; Integrity</span>
          </div>
          <h2 className="font-heading text-[24px] font-semibold text-fg">Local-First Autonomous Architecture</h2>
          <p className="font-body text-[14px] leading-relaxed text-muted">
            Engineered with a scholarly, local-first ethos, your sensitive enterprise datasets remain within your controlled perimeter. Ingestion, statistical computing, and generative reasoning occur directly on your dedicated hardware without external data telemetry.
          </p>
        </section>
      </motion.div>
    </div>
  );
}
