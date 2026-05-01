import React from 'react';
import { motion } from 'framer-motion';
import { Shield, CheckCircle, Database, Brain, BarChart } from 'lucide-react';

export function Methodology() {
  return (
    <div className="max-w-[800px] mx-auto py-20 px-6 font-body text-fg">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="space-y-12"
      >
        <section className="space-y-4 text-center">
          <h1 className="font-heading text-[48px] font-bold tracking-tight">Our Methodology</h1>
          <p className="text-fg/60 text-[18px]">The science behind the insight.</p>
        </section>

        <section className="space-y-8">
          <div className="flex gap-6">
            <div className="shrink-0 w-12 h-12 rounded-full bg-accent/10 flex items-center justify-center text-accent">
              <Database className="w-6 h-6" />
            </div>
            <div className="space-y-2">
              <h3 className="text-[20px] font-semibold">1. Data Ingestion & Sanitization</h3>
              <p className="text-[14px] leading-relaxed text-fg/70">
                GenQ Analytics accepts standard CSV and XLSX formats. Upon upload, our engine performs automated sanitization, handling missing values, standardizing date formats, and normalizing numeric distributions to ensure a clean baseline for analysis.
              </p>
            </div>
          </div>

          <div className="flex gap-6">
            <div className="shrink-0 w-12 h-12 rounded-full bg-accent/10 flex items-center justify-center text-accent">
              <BarChart className="w-6 h-6" />
            </div>
            <div className="space-y-2">
              <h3 className="text-[20px] font-semibold">2. Statistical Synthesis</h3>
              <p className="text-[14px] leading-relaxed text-fg/70">
                We apply a rigorous multi-variate analysis framework. Our engine identifies correlations, detects outliers using Z-score and IQR methods, and builds a comprehensive statistical profile of your dataset. This numeric foundation ensures our AI doesn't hallucinate trends that aren't backed by the math.
              </p>
            </div>
          </div>

          <div className="flex gap-6">
            <div className="shrink-0 w-12 h-12 rounded-full bg-accent/10 flex items-center justify-center text-accent">
              <Brain className="w-6 h-6" />
            </div>
            <div className="space-y-2">
              <h3 className="text-[20px] font-semibold">3. LLM Interpretation</h3>
              <p className="text-[14px] leading-relaxed text-fg/70">
                The synthesized statistical profile is encoded into a high-dimensional context and passed to our dedicated LLM (Gemma 2). The AI acts as a senior data consultant, interpreting the numeric patterns into business narratives, executive summaries, and actionable recommendations.
              </p>
            </div>
          </div>
        </section>

        <section className="p-8 bg-surface rounded-[24px] border border-border space-y-4">
          <div className="flex items-center gap-3 text-accent">
            <Shield className="w-5 h-5" />
            <span className="font-bold text-[12px] uppercase tracking-widest">Privacy & Integrity</span>
          </div>
          <h2 className="text-[24px] font-semibold">Local-First Infrastructure</h2>
          <p className="text-[14px] leading-relaxed text-fg/70">
            Unlike many cloud-based analytics tools, GenQ Analytics leverages local LLM execution. Your sensitive datasets never leave your infrastructure. The analysis is performed entirely in-memory, and results are persisted securely on your machine.
          </p>
        </section>
      </motion.div>
    </div>
  );
}
