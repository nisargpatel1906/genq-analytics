import React, { useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FileText } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/Button';
import { API_URL, apiHeaders } from '../lib/api';
import { useAnalysisStore } from '../store/useAnalysisStore';
import { AgentPipelineTracker } from '../components/AgentPipelineTracker';
import { DiscoveryAlignmentCard } from '../components/DiscoveryAlignmentCard';

export function Upload() {
  const [isDragging, setIsDragging] = useState(false);
  const navigate = useNavigate();

  const {
    status,
    setStatus,
    setProgress,
    jobId,
    setJobId,
    errorMessage,
    setErrorMessage,
    setAgentProgress,
    setAuditScore,
    discoveryProfile,
    setDiscoveryProfile,
    clearJobState,
  } = useAnalysisStore();

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
    setDiscoveryProfile(null);
    
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
        if (data.discovery_profile) {
          setDiscoveryProfile(data.discovery_profile);
          setStatus('awaiting_alignment');
        } else {
          setStatus('analyzing');
        }
      } else {
        setStatus('error');
      }
    } catch (e: any) {
      setStatus('error');
      setErrorMessage(e.message || 'Failed to connect to the backend server.');
    }
  }, [setStatus, setProgress, setJobId, setAgentProgress, setAuditScore, setDiscoveryProfile, setErrorMessage]);

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

  const containerMaxWidth =
    status === 'awaiting_alignment'
      ? 'max-w-[880px]'
      : status !== 'idle' && status !== 'error'
      ? 'max-w-[760px]'
      : 'max-w-[520px]';

  return (
    <div className="w-full h-full flex flex-col items-center justify-start pt-12 pb-20 px-6">
      <div className={`w-full transition-all duration-300 ${containerMaxWidth}`}>
        
        {/* Header (only show when idle or error) */}
        {(status === 'idle' || status === 'error') && (
          <div className="text-center mb-10">
            <h1 className="font-heading text-[40px] font-bold text-fg leading-tight mb-3">
              Initialize Analysis
            </h1>
            <p className="font-body text-[14px] text-fg/60 leading-relaxed">
              Upload your structured dataset to begin the automated insight extraction process. Supported formats: CSV, TSV, XLSX…
            </p>
          </div>
        )}

        {/* State 1: Drop Zone (idle or error) */}
        {status === 'idle' || status === 'error' ? (
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
                {status === 'error' ? 'Analysis Failed' : 'Drop your CSV or Excel'}
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
        ) : null}

        {/* State 2: Business Discovery & Alignment Card */}
        <AnimatePresence>
          {status === 'awaiting_alignment' && discoveryProfile && jobId && (
            <DiscoveryAlignmentCard
              jobId={jobId}
              profile={discoveryProfile}
              onLaunch={() => {
                setStatus('analyzing');
              }}
              onCancel={cancelAnalysis}
            />
          )}
        </AnimatePresence>

        {/* State 3: Autonomous Agent Pipeline Tracker */}
        <AnimatePresence>
          {status !== 'idle' && status !== 'error' && status !== 'awaiting_alignment' && (
            <motion.div
              initial={{ opacity: 0, y: 15 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -15 }}
              className="w-full"
            >
              {jobId ? (
                <AgentPipelineTracker
                  jobId={jobId}
                  onComplete={() => navigate(`/dashboard?job=${jobId}`)}
                  onCancel={cancelAnalysis}
                />
              ) : (
                <div className="p-6 bg-surface border border-border rounded-[16px] flex items-center justify-center gap-3">
                  <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
                  <span className="font-body text-[14px] text-fg font-medium">
                    Pre-scanning dataset schema and generating discovery profile...
                  </span>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

      </div>
    </div>
  );
}
