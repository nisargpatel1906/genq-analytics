import React, { useState, useCallback, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FileText, BarChart2, CheckCircle2, Loader2, Circle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';

type JobStatus = 'idle' | 'uploading' | 'mapping' | 'analyzing' | 'visualizing' | 'complete' | 'error';

export function Upload() {
  const [isDragging, setIsDragging] = useState(false);
  const [status, setStatus] = useState<JobStatus>('idle');
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const navigate = useNavigate();

  const [jobId, setJobId] = useState<string | null>(null);
  const [backendStatus, setBackendStatus] = useState<string>('');
  const [errorMessage, setErrorMessage] = useState<string>('');
  const [dataMeta, setDataMeta] = useState<{rows: number, columns: number} | null>(null);

  useEffect(() => {
    if (!jobId || status === 'error' || status === 'complete') return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/jobs/${jobId}/status`);
        const data = await res.json();
        
        if (data.error || data.status === 'Failed') {
            setStatus('error');
            setErrorMessage(data.error || 'An unknown error occurred during analysis.');
            clearInterval(interval);
            return;
        }

        if (data.status && typeof data.status === 'string' && data.status !== 'Complete' && data.status !== 'Failed') {
            setBackendStatus(data.status);
        }

        if (data.rows && data.columns) {
            setDataMeta({ rows: data.rows, columns: data.columns });
        }

        if (data.step === 1) setStatus('mapping');
        else if (data.step === 2) setStatus('analyzing');
        else if (data.step === 3) setStatus('visualizing');
        else if (data.step === 4 && data.status === 'Complete') {
            setStatus('complete');
            clearInterval(interval);
            setTimeout(() => navigate(`/dashboard?report=${data.report_id}`), 800);
        }
      } catch (e) {
        setStatus('error');
        clearInterval(interval);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [jobId, status, navigate]);

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

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      startUpload(droppedFile);
    }
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      startUpload(selectedFile);
    }
  };

  const startUpload = async (selectedFile: File) => {
    setFile(selectedFile);
    setStatus('uploading');
    setProgress(0);
    setJobId(null);
    
    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      const res = await fetch('http://localhost:8000/api/upload', {
        method: 'POST',
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
  };

  const cancelAnalysis = () => {
    setStatus('idle');
    setFile(null);
    setProgress(0);
    setJobId(null);
    setDataMeta(null);
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
            accept=".csv,.tsv,.json,.xlsx"
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
                <Badge variant="warning">IN PROGRESS</Badge>
              </div>

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
