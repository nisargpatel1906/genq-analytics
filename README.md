<div align="center">

# 📊 GenQ Analytics

**Transform raw datasets into intelligent, interactive reports powered by local AI.**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://reactjs.org/)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20AI-FF6B35)](https://ollama.com/)

[Features](#-features) • [Quick Start](#-quick-start) • [Architecture](#️-architecture) • [Configuration](#-configuration) • [Contributing](#-contributing)

</div>

---

## ✨ Features

- **🤖 AI-Powered Analysis** — Upload any CSV/Excel dataset and get a structured analytical report generated entirely by a local LLM (via Ollama — no cloud API keys required).
- **💬 Context-Aware Chat** — An interactive chat panel lets you ask follow-up questions about your data. The AI is grounded in your specific report, preventing hallucinations.
- **📈 Meaningful Visualizations** — Automatically generates semantically relevant charts (bar, line, scatter, heatmap) based on the actual structure and relationships within your data.
- **📄 PDF Export** — Export polished, chart-embedded PDF reports with a single click.
- **📚 Report Library** — Browse, view, and manage all previously generated reports from a dedicated library page.
- **🔒 100% Local & Private** — All analysis runs on your machine. Your data never leaves your system.

---

## 🚀 Quick Start

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ | [Download](https://www.python.org/downloads/) |
| Node.js | 18+ | [Download](https://nodejs.org/) |
| Ollama | Latest | [Download](https://ollama.com/download) |

### 1. Clone the Repository

```bash
git clone https://github.com/nisargpatel1906/genq-analytics.git
cd genq-analytics
```

### 2. Pull an Ollama Model

Make sure Ollama is running, then pull a model:

```bash
# Recommended (fast, fits on most GPUs)
ollama pull gemma4

# Alternatives
ollama pull llama3.1
ollama pull mistral
```

### 3. Set Up the Backend

```bash
cd backend

# Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\activate        # Windows
# source venv/bin/activate     # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env
# Edit .env and set OLLAMA_MODEL to your pulled model name
```

### 4. Set Up the Frontend

```bash
cd frontend
npm install
```

### 5. Launch the Application

From the project root, run the one-click launcher:

```bash
# Windows
start.bat
```

Or start each server manually:

```bash
# Terminal 1 - Backend (from /backend)
python -m uvicorn main:app --reload --port 8000

# Terminal 2 - Frontend (from /frontend)
npm run dev
```

Open **[http://localhost:5173](http://localhost:5173)** in your browser.

---

## 🏗️ Architecture

```
genq-analytics/
├── backend/                    # FastAPI Python backend
│   ├── app/
│   │   ├── api/
│   │   │   ├── chat.py         # AI chat endpoint (/api/reports/{id}/chat)
│   │   │   ├── export.py       # PDF export endpoint
│   │   │   ├── reports.py      # Report CRUD endpoints
│   │   │   └── upload.py       # Dataset upload & async processing
│   │   └── db.py               # JSON-backed persistent report store
│   ├── services/
│   │   ├── analyzer.py         # Ollama LLM integration & data analysis
│   │   └── visualizer.py       # Chart config generation from data
│   ├── main.py                 # FastAPI application entry point
│   └── requirements.txt
│
├── frontend/                   # React + Vite + TypeScript frontend
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx   # Main dashboard with AI chat panel
│   │   │   ├── Report.tsx      # Report viewer with charts
│   │   │   ├── Library.tsx     # Report library browser
│   │   │   └── Upload.tsx      # Dataset upload UI
│   │   ├── components/
│   │   │   ├── layout/         # Navbar, Footer
│   │   │   └── ui/             # Badge, Button primitives
│   │   └── store/
│   │       └── useChartStore.ts # Zustand chart state management
│   └── package.json
│
├── docker-compose.yml          # Docker orchestration
├── start.bat                   # Windows one-click launcher
└── README.md
```

### How It Works

```
User uploads CSV/Excel
        ↓
  Backend parses file with Pandas
        ↓
  analyzer.py sends data schema + samples to Ollama
        ↓
  Ollama generates structured JSON report
        ↓
  visualizer.py creates semantically relevant chart configs
        ↓
  Report stored in reports_store.json
        ↓
  Frontend renders charts via Recharts
        ↓
  User chats with report via /api/reports/{id}/chat
```

---

## ⚙️ Configuration

### Backend (`backend/.env`)

```env
# Ollama Configuration (required)
OLLAMA_MODEL=gemma4          # Your pulled Ollama model name
OLLAMA_URL=http://localhost:11434  # Ollama server URL (default)
```

### Frontend (`frontend/.env` or root `.env`)

```env
VITE_API_URL=http://localhost:8000  # Backend API URL
VITE_APP_NAME=GenQ Analytics
```

> **Note:** See `.env.example` files in each directory for all available options with descriptions.

---

## 🐳 Docker (Optional)

```bash
docker-compose up --build
```

This starts both the backend (port 8000) and frontend (port 5173). You still need Ollama running on the host.

---

## 📡 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/upload` | Upload a CSV/Excel file for analysis |
| `GET` | `/api/reports` | List all generated reports |
| `GET` | `/api/reports/{id}` | Get a specific report's full data |
| `DELETE` | `/api/reports/{id}` | Delete a report |
| `POST` | `/api/reports/{id}/chat` | Send a chat message in report context |
| `GET` | `/api/reports/{id}/export` | Export report as PDF |

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Commit your changes: `git commit -m 'feat: add some feature'`
4. Push to the branch: `git push origin feature/your-feature-name`
5. Open a Pull Request

Please make sure your code follows the existing style and that the backend and frontend both run without errors.

---

## 📄 License

This project is licensed under the **GNU General Public License v3.0** — see the [LICENSE](LICENSE) file for details.

In short: you are free to use, modify, and distribute this software, but any derivative work must also be released under the GPL v3.

---

## 🙏 Acknowledgements

- [Ollama](https://ollama.com/) — For making local LLM inference simple and accessible.
- [FastAPI](https://fastapi.tiangolo.com/) — High-performance Python web framework.
- [Recharts](https://recharts.org/) — Composable charting library for React.
- [ReportLab](https://www.reportlab.com/) — PDF generation for Python.

---

<div align="center">
Built with ❤️ · <a href="https://github.com/nisargpatel1906/genq-analytics/issues">Report a Bug</a> · <a href="https://github.com/nisargpatel1906/genq-analytics/issues">Request a Feature</a>
</div>
