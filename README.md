<div align="center">

# 📊 GenQ Analytics

**Autonomous Senior Data Analyst AI: Multi-agent causal inference, time-series forecasting, multivariate anomaly detection, clustering, and executive reports.**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://reactjs.org/)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-Multi--LLM-6B46C1)](https://openrouter.ai/)
[![NVIDIA NIM](https://img.shields.io/badge/NVIDIA%20NIM-Cloud%20AI-76B900)](https://www.nvidia.com/en-us/ai/)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20Fallback-FF6B35)](https://ollama.com/)

[Features](#-features) • [Quick Start](#-quick-start) • [Architecture](#️-architecture) • [Configuration](#-configuration) • [API Reference](#-api-reference) • [Contributing](#-contributing)

</div>

---

## ✨ Features

- **🤖 Senior Analyst Autonomous Graph** — A 10-node agentic workflow replacing human data analysts:
  - **Data Profiler & Health Scorer** — Automated missingness, Z-score outlier detection, and A–F data health grading.
  - **Causal Inference Engine** — Identifies intervention/treatment variables, confounding factors, and counterfactual uplift.
  - **Time-Series Forecaster** — Decomposes seasonality, trend drift, and projects 30/60/90-day trajectories with confidence intervals.
  - **Anomaly Detector & Segmenter** — Multivariate outlier isolation and K-Means customer/entity clustering.
  - **Strategic Advisor** — Synthesizes complex analytics into CEO-ready executive headlines and prioritized action matrices.
- **💬 Context-Aware Grounded Chat** — Interactive follow-up Q&A directly against report findings and dataset summaries.
- **📈 Meaningful Visualizations** — Generates publication-ready charts (bar, scatter, regression, box, violin, heatmaps) with Sandboxed Python execution.
- **📄 Multi-Format Export** — Instant export to PDF, Word (.docx), and Jupyter Notebook (.ipynb).
- **📚 Persistent Report Library** — Search, review, and delete historical analysis runs with SQLite storage.
- **🔒 Provider Agnostic** — Native support for OpenRouter, NVIDIA NIM, Google Gemini, Groq, and local Ollama.
- **🛡️ Enterprise Reliability** — Automatic code-repair loops, rate-limit fallback key rotation, and strict schema validation.

---

## 🚀 Quick Start

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ | [Download](https://www.python.org/downloads/) |
| Node.js | 18+ | [Download](https://nodejs.org/) |
| LLM API Key | Active | OpenRouter (free models available), NVIDIA NIM, or Ollama |

### 1. Clone the Repository

```bash
git clone https://github.com/nisargpatel1906/genq-analytics.git
cd genq-analytics
```

### 2. Configure Backend Environment

Copy the example configuration to `backend/.env`:

```bash
copy backend\.env.example backend\.env   # Windows
# cp backend/.env.example backend/.env    # macOS/Linux
```

Set your preferred provider:

```env
# Example: OpenRouter (Default / Free tier available)
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_MODEL=inclusionai/ling-3.0-flash-fin:free
```

*(Alternatively, configure `NVIDIA_API_KEY` for NVIDIA NIM or run local models via `LLM_PROVIDER=ollama`).*

### 3. Set Up the Backend

```bash
cd backend
python -m venv venv
.\venv\Scripts\activate        # Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
```

### 4. Set Up the Frontend

```bash
cd ../frontend
copy .env.example .env         # Windows
# cp .env.example .env          # macOS/Linux

npm install
```

### 5. Launch Application

From the project root:

```bash
# Windows one-click launcher
start.bat
```

Or run services manually in separate terminals:

```bash
# Terminal 1 — Backend (http://localhost:8001)
cd backend && venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# Terminal 2 — Frontend (http://localhost:5173)
cd frontend && npm run dev
```

Open **[http://localhost:5173](http://localhost:5173)** in your browser.

---

## 🏗️ Architecture

```
genq-analytics/
├── backend/                    # FastAPI Python backend
│   ├── app/
│   │   ├── api/                # Endpoints (upload, reports, chat, export)
│   │   ├── db.py               # SQLite-backed persistent report & job store
│   │   └── utils.py            # Numeric coercion & data extraction helpers
│   ├── services/
│   │   ├── agent_graph.py      # LangGraph multi-agent senior analyst pipeline
│   │   ├── agent_prompts.py    # Domain prompts & structured JSON schemas
│   │   ├── analyzer.py         # Data profiling, sampling & quality scoring
│   │   ├── code_executor.py    # Sandboxed Python execution for charts
│   │   └── llm.py              # Multi-provider LLM network client with auto-rotation
│   ├── main.py                 # FastAPI application entry point
│   └── requirements.txt
│
├── frontend/                   # React 19 + Vite + TypeScript frontend
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx   # Live agent progress & context-grounded AI chat
│   │   │   ├── Report.tsx      # Executive report, causal chain, forecast & charts
│   │   │   ├── Library.tsx     # Historical report repository
│   │   │   └── Upload.tsx      # Dataset drag-and-drop ingestion
│   │   ├── components/         # Modular UI badges, buttons, layout
│   │   └── store/
│   │       └── useAnalysisStore.ts # Zustand global state management
│   └── package.json
│
├── test_datasets/              # Realistic dirty/stress-testing mock datasets
│   └── generate_datasets.py    # Deterministic dataset generation script
├── docker-compose.yml          # Containerized deployment
├── start.bat                   # Windows one-click runner
└── README.md
```

### Multi-Agent Pipeline Workflow

```
               [ User Uploads CSV/Excel ]
                          ↓
               [ Ingestion & Normalizer ]
           (Type Coercion & Health Scoring 0–100)
                          ↓
               [ Statistical Profiler ]
         (Normality, Correlations, Group Tests)
                          ↓
          ┌───────────────┴───────────────┐
          ↓                               ↓
   [ Causal Analyst ]             [ Forecaster ]
(Treatment vs Control)        (Seasonality & Horizon)
          ↓                               ↓
   [ Anomaly Detector ]           [ Segmenter ]
(Multivariate Isolation)       (K-Means Clusters)
          └───────────────┬───────────────┘
                          ↓
              [ Visualization Agent ]
          (Seaborn / Matplotlib Sandbox)
                          ↓
              [ Strategic Advisor ]
        (Executive Headline & Priority Matrix)
                          ↓
              [ Quality Auditor & Writer ]
          (Factual Verification & Markdown Stitch)
                          ↓
            [ Final Executive Report ]
       (PDF / Docx / Notebook Export + Live Chat)
```

---

## ⚙️ Configuration Reference

See [`backend/.env.example`](backend/.env.example) and [`frontend/.env.example`](frontend/.env.example) for complete, commented templates.

Key settings include:

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `openrouter` | AI provider (`openrouter`, `nvidia`, `gemini`, `groq`, `ollama`) |
| `OPENROUTER_API_KEY` | - | Primary OpenRouter key |
| `OPENROUTER_FALLBACK_API_KEY` | - | Optional secondary key for seamless 429 rotation |
| `MAX_AGENT_LOOPS` | `6` | Maximum autonomous agent reasoning cycles |
| `CODE_EXEC_TIMEOUT` | `90` | Max seconds allowed for sandbox visualization scripts |
| `GENQ_API_KEY` | `""` | Shared secret header authentication (leave empty for local dev) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Allowed frontend domains |

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/upload` | Upload CSV/Excel dataset and initiate background analysis job |
| `GET` | `/api/jobs/{id}/status` | Poll real-time multi-agent execution step and progress |
| `GET` | `/api/reports` | List all historical reports in library |
| `GET` | `/api/reports/{id}` | Retrieve complete report payload (insights, charts, causal findings) |
| `DELETE` | `/api/reports/{id}` | Permanently delete a report and associated artifacts |
| `POST` | `/api/reports/{id}/chat` | Grounded interactive follow-up Q&A within report context |
| `GET` | `/api/export/{id}` | Download publication-ready PDF report |
| `GET` | `/api/export/{id}/docx` | Download editable Microsoft Word (.docx) report |
| `GET` | `/api/export/{id}/notebook` | Download reproducible Jupyter Notebook (.ipynb) |
| `GET` | `/api/llm/status` | Verify active LLM connection and assigned task models |

---

## 🤝 Contributing

1. Fork the project.
2. Create your feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes (`git commit -m 'feat: Add AmazingFeature'`).
4. Push to the branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

---

## 📄 License

This project is licensed under the **GNU General Public License v3.0** — see the [LICENSE](LICENSE) file for details.

<div align="center">
Built with ❤️ · <a href="https://github.com/nisargpatel1906/genq-analytics/issues">Report an Issue</a>
</div>
