# AI-Powered Website Link Analysis API

Submit a public website URL to get a brand and competitor overview, five target search queries, SEO recommendations, up to five services with evidence, and target audience segments.

## Architecture

```text
POST /link-analysis
  -> URL checks and DNS validation
  -> IP-pinned HTML fetch and optional same-origin crawl
  -> BeautifulSoup extraction and bounded evidence JSON
  -> One Gemini or OpenAI API call with structured JSON
  -> Pydantic validation and evidence checks
  -> Structured JSON response
```

Python 3.11+, FastAPI, Uvicorn, Pydantic v2, Pydantic Settings, HTTPX, BeautifulSoup, the official Google Gen AI and OpenAI SDKs, pytest, pytest-asyncio, and Ruff.

```text
app/
  main.py                      FastAPI routes, lifespan, and error handling
  config.py                    Environment settings
  schemas.py                   Request, response, and provider schemas
  services/
    website_extractor.py       Fetching and extraction
    llm_service.py             Gemini and OpenAI integration
    analysis_service.py         Evidence and pipeline orchestration
    competitor_service.py      Competitor suggestion validation
  utils/validators.py          URL and IP security
tests/                         Offline tests and end-to-end mocked calls
examples/                      Request and response JSON
docs/LLM_COMPARISON.md          Provider research, cost and latency estimates
Dockerfile, render.yaml        Container and Render deployment
```

## Local setup

From this repository's root, create and activate a virtual environment.

```bash
python -m venv .venv
```

Windows PowerShell

```powershell
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

Windows Command Prompt users can activate with `.venv\Scripts\activate`. On macOS or Linux, run `source .venv/bin/activate` and `cp .env.example .env`.

Set `GEMINI_API_KEY` or `OPENAI_API_KEY` in `.env`, then run the API. Gemini takes precedence when both keys are configured. Each analysis calls the selected provider once.

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 4000 --reload
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | Unset | Enables the Gemini Developer API. |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | Gemini model with structured output support. |
| `OPENAI_API_KEY` | Unset | Enables the OpenAI Responses API when the Gemini key is unset. |
| `OPENAI_MODEL` | `gpt-6-luna` | OpenAI Responses model with strict schema and `reasoning.effort=none` support. |
| `LLM_TIMEOUT_SECONDS` | `60` | Total model call deadline, greater than 0 and at most 120 seconds. |
| `HTTP_TIMEOUT_SECONDS` | `15` | Website-stage deadline, greater than 0 and at most 30 seconds. |
| `MAX_WEBSITE_CHARS` | `16000` | Serialized website evidence budget, from 4096 to 32000 characters. |
| `MAX_CRAWL_PAGES` | `4` | Landing page plus up to three relevant same-origin pages. Set 1 for landing page only. |
| `LOG_LEVEL` | `INFO` | Application logging threshold. |

## API

Swagger UI is available at [localhost:4000/docs](http://localhost:4000/docs). `GET /health` returns `{"status":"ok"}` when the process is running. The root path also returns that status.

```bash
curl -fsS http://localhost:4000/link-analysis \
  -H 'Content-Type: application/json' \
  -d @examples/sample_request.json
```

PowerShell

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:4000/link-analysis `
  -ContentType 'application/json' -InFile examples/sample_request.json
```

The [sample response](examples/sample_response.json) uses a fictional IT company to illustrate the shape. It is a test fixture. Live results come from the pages fetched for the request and the provider response.

The response includes the final landing page URL, pages supplied as evidence, and extraction limitations. Services marked `verified` have a matching excerpt on a fetched page. The label describes website support for the service name. Audience suggestions are marked `inferred`. With no external competitor research, competitor suggestions carry names, the `unverified` label, and empty or null evidence fields.

### Errors

The API returns a stable error code and a sanitized message.

```json
{
  "success": false,
  "error": {
    "code": "blocked_destination",
    "message": "Website destination must be public."
  }
}
```

| HTTP | Meaning |
| --- | --- |
| 400 | Malformed URL, unsupported port, or blocked destination |
| 403 / 404 | Source website denied the request or the page was missing |
| 413 | HTML response exceeded 1 MiB |
| 415 | Unsupported content type or content encoding |
| 422 | Invalid request body or unusable static HTML |
| 500 | Unexpected application error |
| 502 | Website DNS, redirect, or gateway failure, or invalid/provider-failed AI response |
| 503 | Provider configuration, authorization, or rate limit |
| 504 | Website or provider timeout |

## Security and cost

- Accept only public HTTP/HTTPS destinations on the default ports. Reject URL credentials, internal names, and private, reserved, loopback, link-local, or mixed public/private DNS results.
- Dial the validated numeric IP with the original HTTP Host and HTTPS certificate hostname. Disable environment proxies and redirect automation. Revalidate each redirect, create a fresh pool per hop, and follow at most three redirects per fetch.
- Use a shared website deadline, a connect timeout of up to five seconds, strict content-type and encoding checks, and a streamed 1 MiB limit per response. Linked pages may fail independently.
- Strip common boilerplate and duplicate text and preserve relevant SEO data, visible content, and selected JSON-LD fields. Only bounded evidence JSON goes to one model call. The model can produce up to 4,500 output tokens.
- Pass untrusted page data in the user message, keep system instructions separate, and give the model zero tools. Schema validation and server-side source checks constrain the returned data. Free-form analysis still depends on the model.
- Store credentials in environment variables. Application logs include duration and token counts. The Responses call sets `store=False`.

See the [model comparison](docs/LLM_COMPARISON.md) for verified prices, quality evidence, and latency assumptions. The default model is GPT-6 Luna at approximately **$0.00150** for 5,000 input and 2,000 output tokens. The manual fallback, GPT-6.1 Terra, is approximately **$0.01500** for the same workload.

## Tests

```bash
python -m pytest -v
python -m ruff check --select E,F,I app tests
python -m ruff format --check app tests
```

Tests mock DNS, website requests, and both provider transports. They cover IP pinning, redirect revalidation, extraction, size and time limits, provider errors, malformed and refused output, schema checks, evidence labels, and prompt role separation. End-to-end tests exercise the HTTP endpoint and both official SDKs using test credentials.

## Deploy to Render

1. Publish this directory as the root of a public GitHub repository and link that repository in **Render Dashboard → New → Blueprint**.
2. Review the Docker web service and plan defined in `render.yaml`. For OpenAI, enter `OPENAI_API_KEY` when prompted. For Gemini, enter `your_api_key_here` at the OpenAI prompt, deploy, then add `GEMINI_API_KEY` in the service's **Environment** tab and choose **Save, rebuild, and deploy**.
3. Copy the service hostname from Render. The container binds to `0.0.0.0` and uses the host-provided `PORT`, with 4000 as the local default.

The expected routes are `https://your-app.onrender.com/`, `/health`, `/docs`, and `POST /link-analysis`. Use your assigned hostname in these smoke commands.

```bash
curl -fsS https://your-app.onrender.com/health
curl -fsS https://your-app.onrender.com/docs
curl -fsS https://your-app.onrender.com/link-analysis \
  -H 'Content-Type: application/json' \
  -d @examples/sample_request.json
```

Optional local Docker smoke test. The container receives credentials from your local `.env`.

```bash
docker build -t ai-link-analysis .
docker run --rm --env-file .env -e PORT=4000 -p 4000:4000 ai-link-analysis
```

[Render Blueprints](https://render.com/docs/blueprint-spec) · [Render web services](https://render.com/docs/web-services)

### GitHub submission

Create an empty public repository on GitHub. From the project directory, run the following and check the staged file list before committing. Use your own repository URL.

```bash
git init -b main
git add .
git diff --cached --name-only
git commit -m "Build website link analysis API"
git remote add origin https://github.com/YOUR_USERNAME/ai-link-analysis.git
git push -u origin main
```

Submit the GitHub repository URL and the Render service URL after verifying the hosted health, Swagger, and analysis routes.

## Known limitations and future improvements

- Static HTML extraction has limited visibility into client-rendered websites and gated or compressed-only pages. Internal discovery favors common English link labels and paths.
- Independent competitor verification and live search metrics require external data. Future research could return sourced comparisons, and a small labeled site corpus could measure extraction and attribution quality.
- This assessment build has a public analysis route with no authentication or caller quotas. Model traffic is billed to the configured account. A production deployment can add gateway quotas and provider budget controls.
- A bounded cache keyed by normalized site content and model version could reduce repeat costs. A browser-based extractor could support JavaScript-heavy sites with its own outbound network controls.
