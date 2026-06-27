import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useAnalysisStore } from './useAnalysisStore';

describe('useAnalysisStore', () => {
  beforeEach(() => {
    // Reset Zustand store state before each test
    useAnalysisStore.getState().clearJobState();
    useAnalysisStore.setState({
      currentReportId: null,
      currentReportData: null,
      currentReportCharts: [],
      isReportLoading: false,
      isChartsLoading: false,
      reportError: '',
      messagesByReportId: {},
    });
    vi.restoreAllMocks();
  });

  it('has correct initial values', () => {
    const state = useAnalysisStore.getState();
    expect(state.jobId).toBeNull();
    expect(state.status).toBe('idle');
    expect(state.progress).toBe(0);
    expect(state.currentReportId).toBeNull();
    expect(state.currentReportData).toBeNull();
    expect(state.currentReportCharts).toEqual([]);
  });

  it('updates job progress status', () => {
    const store = useAnalysisStore.getState();
    store.setJobId('job-123');
    store.setStatus('analyzing');
    store.setProgress(45);

    const updated = useAnalysisStore.getState();
    expect(updated.jobId).toBe('job-123');
    expect(updated.status).toBe('analyzing');
    expect(updated.progress).toBe(45);

    // Test callback progress update
    updated.setProgress((p) => p + 10);
    expect(useAnalysisStore.getState().progress).toBe(55);
  });

  it('clears job state', () => {
    const store = useAnalysisStore.getState();
    store.setJobId('job-123');
    store.setStatus('analyzing');
    store.setProgress(45);

    store.clearJobState();

    const cleared = useAnalysisStore.getState();
    expect(cleared.jobId).toBeNull();
    expect(cleared.status).toBe('idle');
    expect(cleared.progress).toBe(0);
  });

  it('manages chat history correctly', () => {
    const reportId = 'report-abc';
    const store = useAnalysisStore.getState();

    // Check default messages
    const initialMsgs = store.getMessages(reportId);
    expect(initialMsgs.length).toBe(1);
    expect(initialMsgs[0].role).toBe('assistant');
    expect(initialMsgs[0].content).toContain("Ask me anything");

    // Add user message
    store.addMessage(reportId, { role: 'user', content: 'What is the correlation?' });
    expect(useAnalysisStore.getState().getMessages(reportId).length).toBe(2);
    expect(useAnalysisStore.getState().getMessages(reportId)[1]).toEqual({
      role: 'user',
      content: 'What is the correlation?',
    });

    // Clear messages
    store.clearMessages(reportId);
    expect(useAnalysisStore.getState().getMessages(reportId).length).toBe(1);
  });

  it('loads report and charts successfully from stored images', async () => {
    const mockCharts = [{ title: 'Chart 1', interpretation: 'desc', image: 'base64...' }];
    const mockReport = {
      id: 'r-1',
      filename: 'data.csv',
      report: {
        domain: 'finance',
        _meta: {
          chart_images: mockCharts,
        },
      },
    };

    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/reports/r-1')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockReport),
        });
      }
      return Promise.reject(new Error('Unknown url'));
    });

    vi.stubGlobal('fetch', mockFetch);

    const store = useAnalysisStore.getState();
    await store.loadReport('r-1');

    const updated = useAnalysisStore.getState();
    expect(updated.currentReportData).toEqual(mockReport);
    expect(updated.currentReportCharts).toEqual(mockCharts);
    expect(updated.isReportLoading).toBe(false);
    expect(updated.isChartsLoading).toBe(false);
    expect(updated.reportError).toBe('');
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
