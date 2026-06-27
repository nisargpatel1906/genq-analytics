import React, { useState, useCallback, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FileText, BarChart2, CheckCircle2, Loader2, Circle, RefreshCw, ShieldCheck } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { API_URL, apiHeaders } from '../lib/api';
import { useAnalysisStore } from '../store/useAnalysisStore';

export function Upload() {
  const [isDragging, setIsDragging] = useState(false);
  const navigate = useNavigate();

  const {
    status,
    setStatus,
    progress,
    setProgress,
    jobId,
    setJobId,
    backendStatus,
    setBackendStatus,
    errorMessage,
    setErrorMessage,
    dataMeta,
    setDataMeta,
    agentProgress,
    setAgentProgress,
    auditScore,
    setAuditScore,
    clearJobState,
  } = useAnalysisStore();

  useEffect(() => {
    if (!jobId || status === 'error' || status === 'complete') return;

    let active = true;
    let delay = 3000;

    const poll = async () => {
      if (!active) return;
      try {
        const res = await fetch(`${API_URL}/api/jobs/${jobId}/status`, { headers: apiHeaders() });
        const data = await res.json();
        
        if (!active) return;

        if (data.error || data.status === 'Failed') {
            setStatus('error');
            setErrorMessage(data.error || 'An unknown error occurred during analysis.');
            return;
        }

        if (data.status && typeof data.status === 'string' && data.status !== 'Complete' && data.status !== 'Failed') {
            setBackendStatus(data.status);
        }

        if (data.rows && data.columns) {
            setDataMeta({ rows: data.rows, columns: data.columns });
        }
        if (Array.isArray(data.agent_progress)) setAgentProgress(data.agent_progress);
        if (typeof data.audit_score === 'number') setAuditScore(data.audit_score);

        if (data.step === 1) setStatus('mapping');
        else if (data.step === 2) setStatus('analyzing');
        else if (data.step === 3) setStatus('visualizing');
        else if (data.step === 4 && data.status === 'Complete') {
            setStatus('complete');
            setTimeout(() => navigate(`/dashboard?job=${jobId}`), 800);
            return;
        }

        delay = Math.min(delay * 1.5, 15000);
        setTimeout(poll, delay);
      } catch (e) {
        if (active) {
          setStatus('error');
        }
      }
    };

    const timerId = setTimeout(poll, delay);

    return () => {
      active = false;
      clearTimeout(timerId);
    };
  }, [jobId, status, navigate, setStatus, setErrorMessage, setBackendStatus, setDataMeta, setAgentProgress, setAuditScore]);

  useEffect(() => {
    if (status === 'analyzing') {
      const interval = setInterval(() => {
        setProgress((p) => Math.min(p + 5, 100));
      }, 150);
      return () => clearInterval(interval);
    }
  }, [status]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const startUpload = useCallback(async (selectedFile: File) => {
    setStatus('uploading');
    setProgress(0);
    setJobId(null);
    setAgentProgress([]);
    setAuditScore(null);
    
    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      const res = await fetch(`${API_URL}/api/upload`, {
        method: 'POST',
        headers: apiHeaders(),
        body: formData,
      });
      const data = await res.json();
      if (data.job_id) {
        setJobId(data.job_id);
      } else {
        setStatus('error');
      }
    } catch (e: any) {
      setStatus('error');
      setErrorMessage(e.message || 'Failed to connect to the backend server.');
    }
  }, [setStatus, setProgress, setJobId, setAgentProgress, setAuditScore, setErrorMessage]);

  const isValidFile = useCallback((file: File) => {
    const name = file.name.toLowerCase();
    if (!name.endsWith('.csv') && !name.endsWith('.xlsx')) {
      setStatus('error');
      setErrorMessage('Invalid file type. Only CSV and Excel (.xlsx) files are supported.');
      return false;
    }
    return true;
  }, [setStatus, setErrorMessage]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      if (!isValidFile(droppedFile)) return;
      startUpload(droppedFile);
    }
  }, [isValidFile, startUpload]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      if (!isValidFile(selectedFile)) return;
      startUpload(selectedFile);
    }
  };

  const cancelAnalysis = () => {
    if (jobId) {
      fetch(`${API_URL}/api/jobs/${jobId}`, {
        method: 'DELETE',
        headers: apiHeaders(),
      }).catch(err => console.error("Failed to cancel job on backend", err));
    }
    clearJobState();
  };

  return (
    <div className="w-full h-full flex flex-col items-center justify-start pt-16 pb-20 px-6">
      <div className="w-full max-w-[520px]">
        
        {/* Header */}
        <div className="text-center mb-10">
          <h1 className="font-heading text-[40px] font-bold text-fg leading-tight mb-3">
            Initialize Analysis
          </h1>
          <p className="font-body text-[14px] text-fg/60 leading-relaxed">
            Upload your structured dataset to begin the automated insight extraction process. Supported formats: CSV, TSV, JSON…
          </p>
        </div>

        {/* Drop Zone */}
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`relative border-2 border-dashed rounded-[16px] p-12 text-center transition-all ${
            isDragging ? 'border-accent bg-surface/50' : 'border-border bg-surface'
          }`}
        >
          <input
            type="file"
            accept=".csv,.xlsx"
            onChange={handleFileSelect}
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed"
            disabled={status !== 'idle' && status !== 'error'}
          />
          
          <div className="flex flex-col items-center pointer-events-none">
            <FileText className={`w-10 h-10 mb-4 stroke-1 ${status === 'error' ? 'text-error/80' : 'text-accent/60'}`} />
            <h2 className="font-heading text-[22px] text-fg mb-2">
              {status === 'error' ? 'Analysis Failed' : 'Drop your CSV'}
            </h2>
            <p className={`font-body text-[13px] mb-6 ${status === 'error' ? 'text-error/80 max-w-[350px]' : 'text-fg/60'}`}>
              {status === 'error' ? errorMessage : 'or click to browse from your local directory'}
            </p>
            <Button 
              className="pointer-events-auto" 
              disabled={status !== 'idle' && status !== 'error'}
              variant={status === 'error' ? 'secondary' : 'primary'}
            >
              {status === 'error' ? 'Try Again' : 'Select File'}
            </Button>
            <p className="font-body text-[11px] text-fg/40 mt-4">
              Maximum file size: 500MB
            </p>
          </div>
        </div>

        {/* Analysis Progress Panel */}
        <AnimatePresence>
          {status !== 'idle' && status !== 'error' && (
            <motion.div
              initial={{ opacity: 0, y: -20, height: 0 }}
              animate={{ opacity: 1, y: 0, height: 'auto' }}
              exit={{ opacity: 0, y: -20, height: 0 }}
              className="mt-6 bg-surface border border-border rounded-[16px] overflow-hidden"
            >
              {/* Panel Header */}
              <div className="p-5 border-b border-border flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <BarChart2 className="w-5 h-5 text-accent" />
                  <span className="font-body font-medium text-[14px] text-fg">
                    {backendStatus || "AI is analyzing your data..."}
                  </span>
                </div>
                <Badge variant={auditScore !== null ? 'success' : 'warning'}>
                  {auditScore !== null ? `AUDIT ${auditScore}` : 'IN PROGRESS'}
                </Badge>
              </div>

              {agentProgress.length > 0 && (
                <div className="px-5 border-b border-border bg-bg/35">
                  {agentProgress.map((agent) => (
                    <div key={agent.id} className="py-3.5 border-b border-border/60 last:border-0 flex gap-3">
                      <div className="mt-0.5 flex-shrink-0">
                        {agent.status === 'running' ? (
                          agent.round > 0 ? <RefreshCw className="w-4 h-4 text-warning animate-spin" /> : <Loader2 className="w-4 h-4 text-accent animate-spin" />
                        ) : agent.id === 'audit' ? (
                          <ShieldCheck className="w-4 h-4 text-success" />
                        ) : (
                          <CheckCircle2 className="w-4 h-4 text-success" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-3">
                          <h4 className="font-body font-medium text-[13px] text-fg">{agent.name}</h4>
                          <span className="font-body text-[10px] text-fg/50 flex-shrink-0">
                            {agent.score !== undefined ? `${agent.score}/100` : agent.round > 0 ? `Retry ${agent.round}/3` : agent.status}
                          </span>
                        </div>
                        <p className="font-body text-[11px] text-fg/60 mt-1 leading-relaxed">{agent.detail}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Steps List */}
              <div className="px-5">
                
                {/* Step 1: Mapping Schema */}
                <div className="py-4 border-b border-border flex gap-4">
                  <div className="mt-0.5">
                    {status === 'uploading' ? (
                      <Loader2 className="w-4 h-4 text-accent animate-spin" />
                    ) : (
                      <CheckCircle2 className="w-4 h-4 text-success" />
                    )}
                  </div>
                  <div className="flex-1">
                    <h4 className="font-body font-medium text-[14px] text-fg mb-1">Mapping Schema</h4>
                    <p className="font-body text-[12px] text-fg/60">
                      {status === 'uploading' 
                        ? "Ingesting data and analyzing structures..." 
                        : dataMeta ? `Identified ${dataMeta.columns} columns and ${dataMeta.rows.toLocaleString()} rows. Data types inferred.`
                        : "Identified dimensions and mapping schema. Data types inferred."}
                    </p>
                  </div>
                </div>

                {/* Step 2: Detecting Patterns */}
                <div className="py-4 border-b border-border flex gap-4">
                  <div className="mt-0.5">
                    {status === 'uploading' || status === 'mapping' ? (
                      <Circle className="w-4 h-4 text-fg/20" />
                    ) : status === 'analyzing' ? (
                      <Loader2 className="w-4 h-4 text-accent animate-spin" />
                    ) : (
                      <CheckCircle2 className="w-4 h-4 text-success" />
                    )}
                  </div>
                  <div className="flex-1">
                    <h4 className={`font-body font-medium text-[14px] mb-1 ${status === 'uploading' || status === 'mapping' ? 'text-fg/40' : 'text-fg'}`}>
                      Detecting Patterns
                    </h4>
                    <p className={`font-body text-[12px] ${status === 'uploading' || status === 'mapping' ? 'text-fg/30' : 'text-fg/60'}`}>
                      {dataMeta ? `Analyzing correlations and trends across ${dataMeta.columns} metrics.` : "Analyzing correlations and trends across primary metrics."}
                    </p>
                    {status === 'analyzing' && (
                      <div className="mt-3 h-1 w-full bg-border/50 rounded-full overflow-hidden">
                        <motion.div 
                          className="h-full bg-accent rounded-full" 
                          initial={{ width: 0 }}
                          animate={{ width: `${progress}%` }}
                          transition={{ duration: 0.2 }}
                        />
                      </div>
                    )}
                  </div>
                </div>

                {/* Step 3: Generating Visuals */}
                <div className="py-4 flex gap-4">
                  <div className="mt-0.5">
                    {status !== 'visualizing' && status !== 'complete' ? (
                      <Circle className="w-4 h-4 text-fg/20" />
                    ) : status === 'visualizing' ? (
                      <Loader2 className="w-4 h-4 text-accent animate-spin" />
                    ) : (
                      <CheckCircle2 className="w-4 h-4 text-success" />
                    )}
                  </div>
                  <div className="flex-1">
                    <h4 className={`font-body font-medium text-[14px] mb-1 ${status !== 'visualizing' && status !== 'complete' ? 'text-fg/40' : 'text-fg'}`}>
                      Generating Visuals
                    </h4>
                    <p className={`font-body text-[12px] ${status !== 'visualizing' && status !== 'complete' ? 'text-fg/30' : 'text-fg/60'}`}>
                      Constructing preliminary dashboard layouts based on key findings.
                    </p>
                  </div>
                </div>

              </div>

              {/* Panel Footer */}
              <div className="p-4 border-t border-border bg-bg/50 flex justify-end">
                <Button variant="outlined" size="sm" onClick={cancelAnalysis}>
                  Cancel Analysis
                </Button>
              </div>

            </motion.div>
          )}
        </AnimatePresence>

      </div>
    </div>
  );
}
