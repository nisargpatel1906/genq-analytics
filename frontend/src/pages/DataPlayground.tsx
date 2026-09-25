import { useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Database, Play, Loader2, Copy, Check, ChevronDown, ChevronUp,
  Code2, Table2, AlertCircle, Zap, MessageSquare, ChevronRight
} from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { API_URL, apiHeaders } from '../lib/api';
import { useAnalysisStore } from '../store/useAnalysisStore';

interface SQLResult {
  sql: string;
  explanation: string;
  assumptions: string[];
  results: Record<string, any>[];
  row_count: number;
  columns: string[];
  error?: string;
}

const EXAMPLE_QUESTIONS = [
  'What are the top 10 records by revenue?',
  'Show me average values grouped by category',
  'Find all records where the value is above average',
  'Count records by month',
  'What is the correlation between the top two numeric columns?',
  'Show me the 5 most recent entries',
  'Which segment has the highest total revenue?',
  'What percentage of records have missing values?',
];

const CodeBlock = ({ code }: { code: string }) => {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="relative group">
      <pre className="bg-black/60 border border-white/10 rounded-xl p-4 text-xs text-emerald-300 font-mono overflow-x-auto whitespace-pre-wrap leading-relaxed">{code}</pre>
      <button onClick={copy}
        className="absolute top-2 right-2 p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white transition-all opacity-0 group-hover:opacity-100">
        {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
      </button>
    </div>
  );
};

const ResultsTable = ({ columns, rows }: { columns: string[]; rows: Record<string, any>[] }) => {
  const [page, setPage] = useState(0);
  const pageSize = 20;
  const totalPages = Math.ceil(rows.length / pageSize);
  const pageRows = rows.slice(page * pageSize, (page + 1) * pageSize);

  if (rows.length === 0) return (
    <div className="text-center py-8 text-slate-500 text-sm">Query returned 0 rows.</div>
  );

  return (
    <div>
      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-white/[0.04] border-b border-white/10">
              {columns.map(col => (
                <th key={col} className="px-3 py-2.5 text-left font-semibold text-sky-300 whitespace-nowrap">{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row, ri) => (
              <tr key={ri} className={`border-b border-white/5 hover:bg-white/[0.02] transition-colors ${ri % 2 === 0 ? '' : 'bg-white/[0.01]'}`}>
                {columns.map(col => (
                  <td key={col} className="px-3 py-2 text-slate-300 font-mono whitespace-nowrap max-w-[200px] overflow-hidden text-ellipsis">
                    {row[col] === null ? <span className="text-slate-600 italic">null</span> : String(row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between mt-3">
        <p className="text-xs text-slate-500">{rows.length} row{rows.length !== 1 ? 's' : ''} returned{rows.length === 200 ? ' (showing first 200)' : ''}</p>
        {totalPages > 1 && (
          <div className="flex items-center gap-2">
            <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
              className="text-xs px-2 py-1 rounded-lg border border-white/10 text-slate-400 hover:text-white disabled:opacity-30 transition-all">
              ← Prev
            </button>
            <span className="text-xs text-slate-500">Page {page + 1} / {totalPages}</span>
            <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}
              className="text-xs px-2 py-1 rounded-lg border border-white/10 text-slate-400 hover:text-white disabled:opacity-30 transition-all">
              Next →
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export function DataPlayground() {
  const { id } = useParams<{ id?: string }>();
  const { currentReportId, currentReportData } = useAnalysisStore();
  const reportId = id || currentReportId;

  const [question, setQuestion] = useState('');
  const [result, setResult] = useState<SQLResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showSQL, setShowSQL] = useState(true);
  const [history, setHistory] = useState<Array<{ question: string; result: SQLResult }>>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const reportTitle = currentReportData?.report?.title || currentReportData?.filename || 'Dataset';

  const handleQuery = async (q?: string) => {
    const query = q || question;
    if (!query.trim() || !reportId) return;
    setLoading(true);
    setError('');
    setResult(null);

    try {
      const res = await fetch(`${API_URL}/api/reports/${reportId}/nl-sql`, {
        method: 'POST',
        headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: query, dialect: 'sqlite' }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data: SQLResult = await res.json();
      setResult(data);
      setHistory(prev => [{ question: query, result: data }, ...prev.slice(0, 9)]);
    } catch (e: any) {
      setError(e.message || 'Query failed');
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleQuery();
    }
  };

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
                <span className="text-slate-300">Data Playground</span>
              </div>
              <h1 className="text-xl font-bold text-white flex items-center gap-2">
                <Database size={20} className="text-emerald-400" />
                Data Playground
                <span className="text-sm font-normal text-slate-400 ml-1">— {reportTitle}</span>
              </h1>
              <p className="text-xs text-slate-500 mt-0.5">Ask any question in plain English and get live SQL results</p>
            </div>
            <Link to={`/reports/${reportId}`} state={{ openChat: true }}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white transition-all">
              <MessageSquare size={12} /> Chat with Analyst
            </Link>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-6 grid md:grid-cols-[1fr_280px] gap-6">
        {/* Main query area */}
        <div className="space-y-4">
          {/* Question input */}
          <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-4">
            <label className="block text-xs font-semibold text-slate-400 mb-2">
              <Zap size={12} className="inline mr-1.5 text-amber-400" />
              Ask a question about your data
            </label>
            <div className="flex gap-2">
              <input
                ref={inputRef}
                value={question}
                onChange={e => setQuestion(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="e.g. Show me revenue by month for the top 5 categories..."
                className="flex-1 bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-emerald-600/60 transition-all font-mono"
              />
              <button onClick={() => handleQuery()} disabled={!question.trim() || loading || !reportId}
                className="px-5 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white font-semibold text-sm transition-all flex items-center gap-2 whitespace-nowrap">
                {loading ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
                {loading ? 'Running…' : 'Run Query'}
              </button>
            </div>
            {error && (
              <div className="mt-3 flex items-start gap-2 p-3 rounded-xl bg-red-950/30 border border-red-800/30 text-red-400 text-xs">
                <AlertCircle size={13} className="shrink-0 mt-0.5" />
                {error}
              </div>
            )}
          </div>

          {/* Results */}
          <AnimatePresence>
            {result && (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
                {/* Explanation */}
                <div className="bg-white/[0.03] border border-white/8 rounded-2xl p-4">
                  <p className="text-sm text-slate-300 flex items-center gap-2">
                    <Zap size={14} className="text-amber-400 shrink-0" />
                    {result.explanation}
                  </p>
                  {result.assumptions?.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {result.assumptions.map((a, i) => (
                        <span key={i} className="text-[11px] px-2 py-0.5 rounded-full bg-amber-950/30 border border-amber-800/30 text-amber-400">{a}</span>
                      ))}
                    </div>
                  )}
                </div>

                {/* SQL */}
                <div className="bg-white/[0.03] border border-emerald-800/20 rounded-2xl p-4">
                  <button onClick={() => setShowSQL(v => !v)}
                    className="flex items-center justify-between w-full text-sm font-semibold text-emerald-400 mb-3">
                    <span className="flex items-center gap-2"><Code2 size={15} /> Generated SQL</span>
                    {showSQL ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </button>
                  {showSQL && <CodeBlock code={result.sql || ''} />}
                </div>

                {/* Results table */}
                {!result.error && (
                  <div className="bg-white/[0.03] border border-white/8 rounded-2xl p-4">
                    <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
                      <Table2 size={15} className="text-sky-400" />
                      Query Results
                    </h3>
                    <ResultsTable columns={result.columns || []} rows={result.results || []} />
                  </div>
                )}

                {result.error && (
                  <div className="p-4 rounded-2xl bg-red-950/30 border border-red-800/30 text-red-400 text-sm">
                    <p className="font-semibold mb-1">SQL Execution Error</p>
                    <code className="text-xs font-mono">{result.error}</code>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>

          {!result && !loading && (
            <div className="text-center py-16 text-slate-600">
              <Database size={40} className="mx-auto mb-3 opacity-30" />
              <p className="text-sm">Ask a question above to see live SQL results</p>
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          {/* Example questions */}
          <div className="bg-white/[0.03] border border-white/8 rounded-2xl p-4">
            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">Example Questions</h3>
            <div className="space-y-1.5">
              {EXAMPLE_QUESTIONS.map((q, i) => (
                <button key={i} onClick={() => { setQuestion(q); handleQuery(q); }}
                  className="w-full text-left text-xs text-slate-400 hover:text-emerald-400 py-2 px-3 rounded-lg hover:bg-emerald-950/20 transition-all group flex items-center gap-2">
                  <Play size={10} className="shrink-0 opacity-0 group-hover:opacity-100 text-emerald-400 transition-all" />
                  {q}
                </button>
              ))}
            </div>
          </div>

          {/* Query history */}
          {history.length > 0 && (
            <div className="bg-white/[0.03] border border-white/8 rounded-2xl p-4">
              <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">Recent Queries</h3>
              <div className="space-y-1.5">
                {history.slice(0, 6).map((h, i) => (
                  <button key={i} onClick={() => { setQuestion(h.question); setResult(h.result); }}
                    className="w-full text-left text-xs text-slate-400 hover:text-sky-400 py-2 px-3 rounded-lg hover:bg-sky-950/20 transition-all truncate">
                    {h.question}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
