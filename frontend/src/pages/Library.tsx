import { useState, useEffect } from 'react';
import { Search, FileSpreadsheet, FileText, Download, Trash2, ArrowRight, ArrowDown, Loader2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { API_URL, apiHeaders } from '../lib/api';

interface Report {
  id: string;
  name: string;
  status: string;
  date: string;
  rows: number;
  cols: number;
  confidence: number;
}

export function Library() {
  const [searchQuery, setSearchQuery] = useState('');
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchReports = () => {
    setLoading(true);
    fetch(`${API_URL}/api/reports`, { headers: apiHeaders() })
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          setReports(data);
        } else {
          setReports([]);
        }
      })
      .catch(() => setReports([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchReports();
  }, []);

  const handleDelete = async (reportId: string) => {
    if (!window.confirm('Delete this report permanently?')) return;
    try {
      await fetch(`${API_URL}/api/reports/${reportId}`, { method: 'DELETE', headers: apiHeaders() });
      setReports(prev => prev.filter(r => r.id !== reportId));
    } catch {
      alert('Failed to delete report.');
    }
  };

  const filtered = reports.filter(r =>
    r.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="w-full bg-bg min-h-screen py-12 px-6 font-body text-fg">
      <div className="max-w-[1200px] mx-auto">

        {/* Header */}
        <div className="mb-10">
          <h1 className="font-heading text-[40px] md:text-[48px] font-bold text-fg mb-2">Archival Intelligence Library</h1>
          <p className="text-muted text-[16px]">Browse, cross-reference, and inspect synthesized multi-agent analyses</p>
        </div>

        {/* Toolbar */}
        <div className="flex flex-col md:flex-row gap-4 justify-between items-center mb-8 p-4 bg-surface rounded-[12px] border border-border shadow-custom-sm">
          <div className="flex items-center gap-4 w-full md:w-auto">
            {/* Search */}
            <div className="relative w-full md:w-[320px]">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
              <input
                type="text"
                placeholder="Search archival reports..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-surface border border-border rounded-[8px] py-2 pl-9 pr-4 text-[13px] text-fg placeholder:text-muted outline-none focus:border-accent transition-colors shadow-custom-sm"
              />
            </div>
          </div>

          {/* Sort + Refresh */}
          <div className="flex items-center gap-3 w-full md:w-auto justify-end">
            <Button variant="ghost" size="sm" className="gap-2 text-muted hover:text-fg">
              Chronological <ArrowDown className="w-3.5 h-3.5" />
            </Button>
            <Button variant="outlined" size="sm" onClick={fetchReports}>
              Refresh Archives
            </Button>
          </div>
        </div>

        {/* Content */}
        {loading ? (
          <div className="flex items-center justify-center py-32">
            <Loader2 className="w-8 h-8 animate-spin text-accent" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center bg-surface rounded-[12px] border border-border shadow-custom-sm p-8">
            <div className="w-20 h-20 bg-surface-secondary text-accent rounded-full flex items-center justify-center mb-6 border border-border">
              <FileSpreadsheet className="w-10 h-10" />
            </div>
            <h2 className="font-heading text-[28px] font-semibold text-fg mb-3">
              {searchQuery ? 'No matching syntheses found' : 'No archival syntheses yet'}
            </h2>
            <p className="text-muted text-[14px] mb-8 max-w-[440px] leading-relaxed">
              {searchQuery
                ? `No reports match "${searchQuery}". Please refine your search criteria.`
                : 'Deposit your first dataset to initiate an autonomous quantitative synthesis and begin cataloging insights.'}
            </p>
            {!searchQuery && (
              <Link to="/upload">
                <Button variant="primary" size="lg" className="gap-2">
                  Deposit Dataset Now <ArrowRight className="w-4 h-4" />
                </Button>
              </Link>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filtered.map((report) => (
              <div key={report.id} className="bg-surface rounded-[12px] p-6 border border-border shadow-custom-sm hover:shadow-custom-md hover:border-accent/40 transition-all flex flex-col h-full">

                {/* Top Row */}
                <div className="flex items-start justify-between mb-4 gap-3">
                  <div className="flex items-center gap-3 overflow-hidden">
                    <div className="w-10 h-10 rounded-[8px] bg-surface-secondary border border-border flex items-center justify-center text-accent shrink-0">
                      <FileText className="w-5 h-5" />
                    </div>
                    <h3 className="font-heading font-semibold text-[15px] text-fg truncate" title={report.name}>
                      {report.name}
                    </h3>
                  </div>
                  <Badge
                    variant={report.status === 'completed' ? 'success' : report.status === 'processing' ? 'warning' : 'error'}
                    className="shrink-0"
                  >
                    {report.status}
                  </Badge>
                </div>

                {/* Meta Row */}
                <div className="flex items-center justify-between text-[12px] text-muted mb-6 font-mono">
                  <span>{report.date}</span>
                  <span>{report.rows.toLocaleString()} rows × {report.cols} cols</span>
                </div>

                {/* AI Confidence Score */}
                <div className="mt-auto mb-6">
                  <div className="flex justify-between text-[10px] uppercase tracking-wider font-semibold mb-2 font-mono">
                    <span className="text-muted">Extraction Confidence</span>
                    <span className="text-accent">{report.confidence}%</span>
                  </div>
                  <div className="w-full bg-surface-secondary h-1.5 rounded-full overflow-hidden border border-border/40">
                    <div
                      className="bg-accent h-full rounded-full transition-all duration-700"
                      style={{ width: `${report.confidence}%` }}
                    />
                  </div>
                </div>

                {/* Action Row */}
                <div className="flex items-center justify-between pt-4 border-t border-border/60">
                  <div className="flex flex-col gap-1">
                    <Link
                      to={`/reports/${report.id}`}
                      className="text-[13px] font-semibold text-accent hover:text-accent-hover transition-colors font-body"
                    >
                      View Synthesis &rarr;
                    </Link>
                    <Link
                      to={`/dashboard?report=${report.id}`}
                      className="text-[12px] text-muted hover:text-fg transition-colors font-body"
                    >
                      Open in Studio &rarr;
                    </Link>
                  </div>
                  <div className="flex gap-2">
                    <a
                      href={`${API_URL}/api/export/${report.id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="p-2 text-muted hover:text-accent hover:bg-surface-secondary rounded-[6px] transition-colors"
                      title="Download PDF"
                    >
                      <Download className="w-4 h-4" />
                    </a>
                    <button
                      className="p-2 text-muted hover:text-error hover:bg-error/10 rounded-[6px] transition-colors"
                      title="Delete Report"
                      onClick={() => handleDelete(report.id)}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

              </div>
            ))}
          </div>
        )}

      </div>
    </div>
  );
}
