# File Extractor / Nova Flask worker

Flask + Celery worker used by Nova for:

1. **File text extraction** (`/extract`, `/extract-base64`)
2. **Chatbot Exact document processing** (`/chatbot-document-processing`)
3. **R2R accounting agent** (`/r2r/accounting-agent/enqueue`)

**Environment variables:** see [`ENVIRONMENT.md`](./ENVIRONMENT.md) (complete list with descriptions). Copy `env.example` to `.env`.

## Layout

```text
app.py                    # Flask factory (gunicorn app:app)
celery_app.py / tasks.py  # Celery worker (concurrency=2)
routes/                   # HTTP blueprints
shared/                   # Cross-domain helpers (Supabase URLs)
provider/                 # ERP layer (router + exact adapter)
  router.py               # switch on connected ERP (Exact today)
  exact/                  # Exact Online (OData, tokens, POs, journals, documents)
fileExtraction/           # PDF/DOCX/CSV/XLSX extractors
chatbot/                  # Document body pipeline (uses provider.exact.documents)
r2r/                      # Accounting agent (uses provider.router / provider.exact)
tests/
ENVIRONMENT.md
```

## Features

- Extract text content from PDF, DOC, DOCX, CSV, TXT, XLSX
- Queue Exact document body filling (Celery)
- Queue R2R month-end / month-start close jobs (Celery Python agent)
- API key authentication and rate limiting
- URL validation to reduce SSRF risk
- Configurable file size limits

## Installation

1. Clone the repository:
```bash
git clone <your-repo-url>
cd extractor-server
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
# Copy the example environment file
cp env.example .env

# Edit .env and set your API key
# FILE_EXTRACTOR_KEY=your-secret-api-key-here
```

**Note:** If `FILE_EXTRACTOR_KEY` is not set in `.env`, authentication will be disabled (not recommended for production).

## Running the Server

### Development Mode
```bash
python app.py
```

The server will start on `http://localhost:5000`

### Production Mode (with Gunicorn)
```bash
gunicorn app:app
```

## Using the Production API

The API is deployed and available at: **https://file-extractor-0jxu.onrender.com/**

You can use it directly without running the server locally. Simply replace `http://localhost:5000` with `https://file-extractor-0jxu.onrender.com` in all examples below.

### Quick Test

Test the production API:
```bash
curl https://file-extractor-0jxu.onrender.com/
```

Check health status:
```bash
curl https://file-extractor-0jxu.onrender.com/health
```

### Extract from File (Production)

**GET Request:**
```bash
curl -X GET "https://file-extractor-0jxu.onrender.com/extract?url=https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
```

**POST Request:**
```bash
curl -X POST https://file-extractor-0jxu.onrender.com/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"}'
```

### Production API Examples

**Extract from PDF:**
```bash
curl -X GET "https://file-extractor-0jxu.onrender.com/extract?url=https://example.com/document.pdf"
```

**Extract from CSV:**
```bash
curl -X POST https://file-extractor-0jxu.onrender.com/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://raw.githubusercontent.com/datasets/covid-19/main/data/time-series-19-covid-combined.csv"}'
```

**Extract from TXT:**
```bash
curl -X GET "https://file-extractor-0jxu.onrender.com/extract?url=https://www.gutenberg.org/files/1342/1342-0.txt"
```

## API Endpoints

### 1. Root Endpoint
Get API information:
```bash
GET /
```

### 2. Health Check
Check server status and supported formats:
```bash
GET /health
```

### 3. Extract Content
Extract content from a file URL (requires API key authentication):

**GET Request:**
```bash
GET /extract?url=<file_url>
Authorization: Bearer <your-api-key>
```

**POST Request:**
```bash
POST /extract
Content-Type: application/json
Authorization: Bearer <your-api-key>

{
  "url": "<file_url>"
}
```

**Note:** The API key can be provided in two formats:
- `Authorization: Bearer <your-api-key>` (recommended)
- `Authorization: <your-api-key>` (also supported)

## Usage Examples

### Extract from PDF (GET)

**Production API:**
```bash
curl -X GET "https://file-extractor-0jxu.onrender.com/extract?url=https://example.com/document.pdf" \
  -H "Authorization: Bearer your-api-key-here"
```

**Local Server:**
```bash
curl -X GET "http://localhost:5000/extract?url=https://example.com/document.pdf" \
  -H "Authorization: Bearer your-api-key-here"
```

### Extract from CSV (POST)

**Production API:**
```bash
curl -X POST https://file-extractor-0jxu.onrender.com/extract \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key-here" \
  -d '{"url": "https://example.com/data.csv"}'
```

**Local Server:**
```bash
curl -X POST http://localhost:5000/extract \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key-here" \
  -d '{"url": "https://example.com/data.csv"}'
```

### Extract from TXT file

**Production API:**
```bash
curl -X GET "https://file-extractor-0jxu.onrender.com/extract?url=https://example.com/file.txt"
```

**Local Server:**
```bash
curl -X GET "http://localhost:5000/extract?url=https://example.com/file.txt"
```

### Extract from DOCX file

**Production API:**
```bash
curl -X POST https://file-extractor-0jxu.onrender.com/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/document.docx"}'
```

**Local Server:**
```bash
curl -X POST http://localhost:5000/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/document.docx"}'
```

## Response Format

### Success Response
```json
{
  "success": true,
  "content": "Extracted text content here...",
  "file_type": ".pdf",
  "content_length": 1234
}
```

### Error Response
```json
{
  "error": "Error message here"
}
```

## Supported File Types

- **PDF** (`.pdf`) - Extracts text using pypdf
- **DOCX** (`.docx`) - Extracts text using python-docx
- **DOC** (`.doc`) - Extracts text using docx2python
- **CSV** (`.csv`) - Extracts all rows as text
- **TXT** (`.txt`) - Extracts plain text content
- **XLSX** (`.xlsx`) - Extracts cell values from all sheets using openpyxl

## Testing

```bash
pytest                    # all tests under tests/
pytest tests/test_api.py -v
python run_local_extract.py   # manual JSON output for testing_files/*
```

## Deployment to Render

This project includes a `render.yaml` configuration file for easy deployment to Render.

1. Push your code to GitHub/GitLab
2. In Render dashboard, create a new Web Service
3. Connect your repository
4. Render will automatically detect the `render.yaml` file
5. The service will be deployed automatically

The `render.yaml` file configures:
- Python environment
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Free tier plan

## Environment Variables

See **[`ENVIRONMENT.md`](./ENVIRONMENT.md)** for every variable this server reads, including chatbot and R2R accounting-agent secrets.

Quick start:

```bash
cp env.example .env
```

Minimum for `/extract`:

```env
FILE_EXTRACTOR_KEY=your-secret-api-key-here
```

Worker secrets: copy `env.celery.example`. File size, timeouts, models, and Exact pacing live in Python constants, not `.env`.

## Error Handling

The API handles various error cases:
- Missing URL parameter
- Invalid or unreachable URLs
- Unsupported file types
- Extraction failures
- HTTP errors (404, 500, etc.)

## Example with Python

**Using Production API:**
```python
import requests
import os

# Get API key from environment variable or set directly
API_KEY = os.environ.get('FILE_EXTRACTOR_KEY', 'your-api-key-here')

# Extract content from a file URL using production API
response = requests.post(
    'https://file-extractor-0jxu.onrender.com/extract',
    json={'url': 'https://example.com/document.pdf'},
    headers={'Authorization': f'Bearer {API_KEY}'}
)

if response.status_code == 200:
    data = response.json()
    print(f"File type: {data['file_type']}")
    print(f"Content length: {data['content_length']}")
    print(f"Content:\n{data['content']}")
elif response.status_code == 401:
    print("Authentication failed. Check your API key.")
else:
    print(f"Error: {response.json()['error']}")
```

**Using Local Server:**
```python
import requests

# Extract content from a file URL
response = requests.post(
    'http://localhost:5000/extract',
    json={'url': 'https://example.com/document.pdf'}
)

if response.status_code == 200:
    data = response.json()
    print(f"File type: {data['file_type']}")
    print(f"Content length: {data['content_length']}")
    print(f"Content:\n{data['content']}")
else:
    print(f"Error: {response.json()['error']}")
```

## Example with JavaScript/Node.js

**Using Production API:**
```javascript
const API_KEY = process.env.FILE_EXTRACTOR_KEY || 'your-api-key-here';

async function extractFile(url) {
  const response = await fetch('https://file-extractor-0jxu.onrender.com/extract', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${API_KEY}`
    },
    body: JSON.stringify({ url: url })
  });

  const data = await response.json();
  
  if (data.success) {
    console.log('File type:', data.file_type);
    console.log('Content:', data.content);
  } else {
    console.error('Error:', data.error);
  }
}

extractFile('https://example.com/document.pdf');
```

**Using Local Server:**
```javascript
async function extractFile(url) {
  const response = await fetch('http://localhost:5000/extract', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ url: url })
  });

  const data = await response.json();
  
  if (data.success) {
    console.log('File type:', data.file_type);
    console.log('Content:', data.content);
  } else {
    console.error('Error:', data.error);
  }
}

extractFile('https://example.com/document.pdf');
```

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
