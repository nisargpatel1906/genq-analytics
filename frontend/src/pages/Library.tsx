import React, { useState, useEffect } from 'react';
import { Search, FileSpreadsheet, FileText, Download, Trash2, ArrowRight, ArrowDown, Loader2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';

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
    fetch('http://localhost:8000/api/reports')
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
      await fetch(`http://localhost:8000/api/reports/${reportId}`, { method: 'DELETE' });
      setReports(prev => prev.filter(r => r.id !== reportId));
    } catch {
      alert('Failed to delete report.');
    }
  };

  const filtered = reports.filter(r =>
    r.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="w-full bg-[#FAFAFA] min-h-full py-12 px-6 font-body">
      <div className="max-w-[1200px] mx-auto">

        {/* Header */}
        <div className="mb-10">
          <h1 className="font-heading text-[48px] font-bold text-fg mb-2">Analysis Library</h1>
          <p className="text-fg/70 text-[16px]">Browse and manage your uploaded analyses</p>
        </div>

        {/* Toolbar */}
        <div className="flex flex-col md:flex-row gap-4 justify-between items-center mb-8 p-4 bg-surface rounded-[12px] border border-border shadow-sm">
          <div className="flex items-center gap-4 w-full md:w-auto">
            {/* Search */}
            <div className="relative w-full md:w-[300px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-fg/50" />
              <input
                type="text"
                placeholder="Search reports..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-bg border border-border rounded-md py-2 pl-9 pr-4 text-[14px] outline-none focus:border-accent transition-colors"
              />
            </div>
          </div>

          {/* Sort + Refresh */}
          <div className="flex items-center gap-3 w-full md:w-auto justify-end">
            {/* TODO: Implement date-based sorting */}
            <Button variant="ghost" className="gap-2 text-fg py-2 h-auto text-[13px]">
              Latest <ArrowDown className="w-3.5 h-3.5" />
            </Button>
            <Button variant="outlined" className="gap-2 py-2 h-auto text-[13px]" onClick={fetchReports}>
              Refresh
            </Button>
          </div>
        </div>

        {/* Content */}
        {loading ? (
          <div className="flex items-center justify-center py-32">
            <Loader2 className="w-8 h-8 animate-spin text-accent" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="w-20 h-20 bg-accent/10 text-accent rounded-full flex items-center justify-center mb-6">
              <FileSpreadsheet className="w-10 h-10" />
            </div>
            <h2 className="font-heading text-[32px] font-semibold text-fg mb-3">
              {searchQuery ? 'No matching reports' : 'No analyses yet'}
            </h2>
            <p className="text-fg/70 text-[14px] mb-8 max-w-[400px]">
              {searchQuery
                ? `No reports match "${searchQuery}". Try a different search.`
                : 'Upload your first dataset to generate an AI-powered report and start uncovering insights.'}
            </p>
            {!searchQuery && (
              <Link to="/upload">
                <Button variant="primary" className="gap-2">
                  Upload Now <ArrowRight className="w-4 h-4" />
                </Button>
              </Link>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filtered.map((report) => (
              <div key={report.id} className="bg-surface rounded-[12px] p-6 border border-border/70 shadow-sm hover:shadow-md transition-shadow flex flex-col h-full">

                {/* Top Row */}
                <div className="flex items-start justify-between mb-4 gap-3">
                  <div className="flex items-center gap-3 overflow-hidden">
                    <div className="w-10 h-10 rounded-md bg-accent/10 flex items-center justify-center text-accent shrink-0">
                      <FileText className="w-5 h-5" />
                    </div>
                    <h3 className="font-medium text-[14px] truncate" title={report.name}>
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
                <div className="flex items-center justify-between text-[12px] text-fg/60 mb-6">
                  <span>{report.date}</span>
                  <span>{report.rows.toLocaleString()} rows × {report.cols} cols</span>
                </div>

                {/* AI Confidence Score */}
                <div className="mt-auto mb-6">
                  <div className="flex justify-between text-[11px] uppercase tracking-widest font-medium mb-2">
                    <span className="text-fg/60">AI Confidence</span>
                    <span className="text-accent">{report.confidence}%</span>
                  </div>
                  <div className="w-full bg-border h-1.5 rounded-full overflow-hidden">
                    <div
                      className="bg-accent h-full rounded-full transition-all duration-700"
                      style={{ width: `${report.confidence}%` }}
                    />
                  </div>
                </div>

                {/* Action Row */}
                <div className="flex items-center justify-between pt-4 border-t border-border/50">
                  <div className="flex flex-col gap-1">
                    <Link
                      to={`/reports/${report.id}`}
                      className="text-[13px] font-medium text-accent hover:text-accent-hover transition-colors"
                    >
                      View Report →
                    </Link>
                    <Link
                      to={`/dashboard?report=${report.id}`}
                      className="text-[12px] text-fg/50 hover:text-fg transition-colors"
                    >
                      Open on Dashboard →
                    </Link>
                  </div>
                  <div className="flex gap-2">
                    <a
                      href={`http://localhost:8000/api/export/${report.id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="p-2 text-fg/50 hover:text-accent hover:bg-accent/10 rounded-md transition-colors"
                      title="Download PDF"
                    >
                      <Download className="w-4 h-4" />
                    </a>
                    <button
                      className="p-2 text-fg/50 hover:text-error hover:bg-error/10 rounded-md transition-colors"
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
