# DPIAforge
### by ALI MOYO

A professional Data Protection Impact Assessment (DPIA) platform powered by AI.

## Features

- 🛡️ Create & manage DPIAs with guided multi-step forms
- ⚖️ Supports 6 regulations: GDPR, Zimbabwe CDPA, South Africa POPIA, UAE PDPL, Saudi PDPL, Qatar DPL
- 🤖 AI-powered research & full DPIA generation
- 📄 Export every DPIA as a formatted Word (.docx) document
- 💾 SQLite database — zero setup required
- 🎨 Clean, professional UI with Deep Blue / Cyan colour scheme

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure your AI provider
```bash
cp .env.example .env
# Edit .env and add your API key
```

**.env example:**
```
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-5
SECRET_KEY=your-random-secret-key
```

### 3. Run the app
```bash
python app.py
```

Open http://localhost:5000 in your browser.

## AI Provider Setup

Edit `.env` and set `AI_PROVIDER` to one of:

| Provider  | Variable          | Model               |
|-----------|-------------------|---------------------|
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-opus-4-5` |
| `openai`  | `OPENAI_API_KEY`  | `gpt-4o`            |
| `gemini`  | `GEMINI_API_KEY`  | `gemini-1.5-pro`    |

## Project Structure

```
dpiaforge/
├── app.py              # Flask routes & app entry
├── database.py         # SQLite database layer
├── ai_service.py       # AI provider abstraction
├── docx_export.py      # Word document generator
├── requirements.txt
├── .env.example
└── templates/
    ├── base.html
    ├── dashboard.html
    ├── dpia_list.html
    ├── dpia_form.html
    └── dpia_detail.html
```

## Supported Regulations

- **GDPR** — EU General Data Protection Regulation 2016/679
- **Zimbabwe CDPA** — Cyber and Data Protection Act [Chapter 12:07]
- **South Africa POPIA** — Protection of Personal Information Act 4 of 2013
- **UAE PDPL** — Federal Decree-Law No. 45 of 2021
- **Saudi PDPL** — Personal Data Protection Law (Royal Decree M/19)
- **Qatar DPL** — Personal Data Privacy Protection Law No. 13 of 2016
