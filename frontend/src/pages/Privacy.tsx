import { motion } from 'framer-motion';

export function DataPrivacy() {
  return (
    <div className="max-w-[800px] mx-auto py-20 px-6 font-body text-fg">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-8">
        <h1 className="font-heading text-[40px] font-bold">Data Privacy</h1>
        <p className="text-fg/60">Last updated: April 30, 2026</p>
        
        <div className="space-y-6 text-[15px] leading-relaxed text-fg/80">
          <section className="space-y-3">
            <h2 className="text-[20px] font-semibold text-fg">1. Data Ownership</h2>
            <p>You retain full ownership of all data uploaded to GenQ Analytics. We do not claim any rights to your datasets, reports, or generated insights.</p>
          </section>

          <section className="space-y-3">
            <h2 className="text-[20px] font-semibold text-fg">2. Local Processing</h2>
            <p>GenQ Analytics is designed with a local-first philosophy. All data processing, statistical analysis, and LLM interpretation occur on your local machine or dedicated infrastructure. We do not transmit your raw datasets to external servers.</p>
          </section>

          <section className="space-y-3">
            <h2 className="text-[20px] font-semibold text-fg">3. Information We Collect</h2>
            <p>The only data we collect is anonymized usage statistics to improve our algorithms, such as processing time and success rates of analysis jobs. This does not include any identifiable information from your datasets.</p>
          </section>
        </div>
      </motion.div>
    </div>
  );
}
