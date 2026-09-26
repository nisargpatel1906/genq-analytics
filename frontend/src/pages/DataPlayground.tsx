import { useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Database, Play, Loader2, Copy, Check, ChevronDown, ChevronUp,
  Code2, Table2, AlertCircle, Zap, MessageSquare, ChevronRight
} from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { API_URL, apiHeaders } from '../lib/api';
import { useAnalysisStore } from '../store/useAnalysisStore';
import { Button } from '../components/ui/Button';

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
  'Which segment has the highest total volume?',
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
      <pre className="bg-[#1A1208] border border-border/40 rounded-[8px] p-4 text-xs text-[#EDE4D0] font-mono overflow-x-auto whitespace-pre-wrap leading-relaxed shadow-custom-sm">{code}</pre>
      <button
        onClick={copy}
        className="absolute top-2.5 right-2.5 p-1.5 rounded-[6px] bg-surface-secondary/20 hover:bg-surface-secondary/40 text-accent transition-all opacity-0 group-hover:opacity-100"
      >
        {copied ? <Check size={13} className="text-success" /> : <Copy size={13} />}
      </button>
    </div>
  );
};

const ResultsTable = ({ columns, rows }: { columns: string[]; rows: Record<string, any>[] }) => {
  const [page, setPage] = useState(0);
  const pageSize = 20;
  const totalPages = Math.ceil(rows.length / pageSize);
  const pageRows = rows.slice(page * pageSize, (page + 1) * pageSize);

  if (rows.length === 0)
    return (
      <div className="text-center py-8 text-muted text-sm font-body">Query returned zero rows.</div>
    );

  return (
    <div>
      <div className="overflow-x-auto rounded-[8px] border border-border">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-surface-secondary/80 border-b border-border">
              {columns.map(col => (
                <th key={col} className="px-3.5 py-2.5 text-left font-semibold text-fg whitespace-nowrap font-heading">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row, ri) => (
              <tr
                key={ri}
                className={`border-b border-border/60 hover:bg-surface-secondary/30 transition-colors ${
                  ri % 2 === 0 ? 'bg-surface' : 'bg-surface-secondary/10'
                }`}
              >
                {columns.map(col => (
                  <td key={col} className="px-3.5 py-2 text-fg font-mono whitespace-nowrap max-w-[220px] overflow-hidden text-ellipsis">
                    {row[col] === null ? <span className="text-muted/60 italic">null</span> : String(row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between mt-3 px-1">
        <p className="text-xs text-muted font-body">
          {rows.length} row{rows.length !== 1 ? 's' : ''} returned{rows.length === 200 ? ' (showing first 200)' : ''}
        </p>
        {totalPages > 1 && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="text-xs px-2.5 py-1 rounded-[6px] border border-border bg-surface text-fg hover:bg-surface-secondary disabled:opacity-30 transition-all font-body font-medium"
            >
              &larr; Prev
            </button>
            <span className="text-xs text-muted font-body">
              Page {page + 1} of {totalPages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="text-xs px-2.5 py-1 rounded-[6px] border border-border bg-surface text-fg hover:bg-surface-secondary disabled:opacity-30 transition-all font-body font-medium"
            >
              Next &rarr;
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

  const reportTitle = currentReportData?.report?.title || currentReportData?.filename || 'Dataset Repository';

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
      setError(e.message || 'Execution failed');
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
    <div className="min-h-screen bg-bg text-fg font-body">
      {/* Header */}
      <div className="border-b border-border bg-surface/90 backdrop-blur-md sticky top-0 z-20 shadow-custom-sm">
        <div className="max-w-6xl mx-auto px-6 py-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-xs text-muted mb-1">
                <Link to={`/reports/${reportId}`} className="hover:text-accent transition-colors font-medium">Synthesis Report</Link>
                <ChevronRight size={12} />
                <span className="text-fg font-medium">Data Query Studio</span>
              </div>
              <h1 className="font-heading text-2xl font-bold text-fg flex items-center gap-2.5">
                <Database size={20} className="text-accent" />
                Data Query Studio
                <span className="text-sm font-normal font-body text-muted ml-1">— {reportTitle}</span>
              </h1>
              <p className="font-body text-xs text-muted mt-1">Inquire in natural language; our autonomous engine synthesizes SQL and renders query matrices</p>
            </div>
            <Link to={`/reports/${reportId}`} state={{ openChat: true }}>
              <Button variant="outlined" size="sm" className="gap-1.5">
                <MessageSquare size={12} /> Consult Analyst
              </Button>
            </Link>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-8 grid md:grid-cols-[1fr_280px] gap-6">
        {/* Main query area */}
        <div className="space-y-4">
          {/* Question input */}
          <div className="bg-surface border border-border rounded-[12px] p-5 shadow-custom-sm">
            <label className="block text-xs font-semibold text-fg uppercase tracking-[0.06em] mb-2 font-heading">
              <Zap size={12} className="inline mr-1.5 text-accent" />
              Inquire into your dataset
            </label>
            <div className="flex gap-2.5">
              <input
                ref={inputRef}
                value={question}
                onChange={e => setQuestion(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="e.g. Show me revenue by month for the top 5 categories..."
                className="flex-1 bg-surface border border-border rounded-[8px] px-4 py-2.5 text-sm text-fg placeholder:text-muted focus:outline-none focus:border-accent transition-all shadow-custom-sm font-body"
              />
              <Button
                onClick={() => handleQuery()}
                disabled={!question.trim() || loading || !reportId}
                variant="primary"
                size="md"
                className="gap-2 whitespace-nowrap"
              >
                {loading ? <Loader2 size={15} className="animate-spin" /> : <Play size={14} />}
                {loading ? 'Synthesizing…' : 'Execute Query'}
              </Button>
            </div>

            {error && (
              <div className="mt-3.5 flex items-start gap-2 p-3.5 rounded-[8px] bg-error/10 border border-error/30 text-error text-xs">
                <AlertCircle size={14} className="shrink-0 mt-0.5" />
                <span className="font-medium">{error}</span>
              </div>
            )}
          </div>

          {/* Results */}
          <AnimatePresence>
            {result && (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
                {/* Explanation */}
                <div className="bg-surface border border-border rounded-[12px] p-4 shadow-custom-sm">
                  <p className="font-body text-sm text-fg flex items-center gap-2">
                    <Zap size={14} className="text-accent shrink-0" />
                    {result.explanation}
                  </p>
                  {result.assumptions?.length > 0 && (
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {result.assumptions.map((a, i) => (
                        <span key={i} className="text-[11px] px-2.5 py-0.5 rounded-[4px] bg-surface-secondary border border-border text-accent font-body">
                          {a}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* SQL */}
                <div className="bg-surface border border-border rounded-[12px] p-4 shadow-custom-sm">
                  <button
                    onClick={() => setShowSQL(v => !v)}
                    className="flex items-center justify-between w-full text-sm font-semibold text-accent mb-3 font-heading"
                  >
                    <span className="flex items-center gap-2"><Code2 size={15} /> Synthesized SQL Formulation</span>
                    {showSQL ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </button>
                  {showSQL && <CodeBlock code={result.sql || ''} />}
                </div>

                {/* Results table */}
                {!result.error && (
                  <div className="bg-surface border border-border rounded-[12px] p-4 shadow-custom-sm">
                    <h3 className="font-heading text-sm font-semibold text-fg mb-4 flex items-center gap-2">
                      <Table2 size={15} className="text-accent" />
                      Empirical Query Matrix
                    </h3>
                    <ResultsTable columns={result.columns || []} rows={result.results || []} />
                  </div>
                )}

                {result.error && (
                  <div className="p-4 rounded-[12px] bg-error/10 border border-error/30 text-error text-sm">
                    <p className="font-semibold mb-1 font-heading">SQL Execution Exception</p>
                    <code className="text-xs font-mono">{result.error}</code>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>

          {!result && !loading && (
            <div className="text-center py-20 text-muted bg-surface rounded-[12px] border border-border shadow-custom-sm">
              <Database size={36} className="mx-auto mb-3 opacity-30 text-accent" />
              <p className="font-heading text-base text-fg">Inquire above to synthesize and execute live SQL</p>
              <p className="text-xs text-muted mt-1 font-body">Supports aggregation, filtering, rankings, and statistical distributions</p>
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          {/* Example questions */}
          <div className="bg-surface border border-border rounded-[12px] p-4 shadow-custom-sm">
            <h3 className="text-xs font-bold text-muted uppercase tracking-[0.08em] mb-3 font-body">Example Inquiries</h3>
            <div className="space-y-1">
              {EXAMPLE_QUESTIONS.map((q, i) => (
                <button
                  key={i}
                  onClick={() => { setQuestion(q); handleQuery(q); }}
                  className="w-full text-left text-xs text-muted hover:text-accent py-2 px-2.5 rounded-[6px] hover:bg-surface-secondary/60 transition-all group flex items-center gap-2 font-body"
                >
                  <Play size={10} className="shrink-0 opacity-0 group-hover:opacity-100 text-accent transition-all" />
                  <span>{q}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Query history */}
          {history.length > 0 && (
            <div className="bg-surface border border-border rounded-[12px] p-4 shadow-custom-sm">
              <h3 className="text-xs font-bold text-muted uppercase tracking-[0.08em] mb-3 font-body">Recent Inquiries</h3>
              <div className="space-y-1">
                {history.slice(0, 6).map((h, i) => (
                  <button
                    key={i}
                    onClick={() => { setQuestion(h.question); setResult(h.result); }}
                    className="w-full text-left text-xs text-muted hover:text-accent py-2 px-2.5 rounded-[6px] hover:bg-surface-secondary/60 transition-all truncate font-body"
                  >
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
