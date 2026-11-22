# LLM comparison

Prices were checked on 22 November 2026. Figures use standard online, uncached text prices in USD per million tokens. The sample request uses 5,000 input tokens and 2,000 output tokens. Cost = 0.005 × input price + 0.002 × output price. Hosting, tools, taxes, and repeated requests are outside this estimate.

| Provider and model | Input / output per million | Context or input capacity | Structured JSON | Sample cost |
| --- | ---: | ---: | --- | ---: |
| OpenAI GPT-6 Luna (`gpt-6-luna`) | $0.10 / $0.50 | 1,050,000 context | Strict JSON Schema via Responses API | $0.00150 |
| OpenAI GPT-6.1 Terra (`gpt-6.1-terra`) | $1.00 / $5.00 | 1,050,000 context | Strict JSON Schema via Responses API | $0.01500 |
| Google Gemini 3.1 Flash-Lite (`gemini-3.1-flash-lite`) | $0.25 / $1.50 | 1,048,576 input | Structured output with a supported JSON Schema subset | $0.00425 |
| Anthropic Claude Haiku 5.5 (`claude-haiku-5-5`) | $0.10 / $0.50 | 1,000,000 context | Structured JSON output via Messages API | $0.00150 |

The Claude rate shown applies to prompts up to 100,000 input tokens. Google's output price includes thinking tokens. Actual token counts can differ across providers for the same input. [OpenAI pricing](https://developers.openai.com/api/docs/pricing) · [Google pricing](https://ai.google.dev/gemini-api/docs/pricing) · [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing)

## Quality and speed evidence

- **GPT-6 Luna** targets focused, high-volume workloads and supports strict structured output with reasoning disabled. OpenAI reports a length-adjusted HealthBench Professional score of 60.8, up 5.1 points from GPT-5.6 Luna, and mixed results across the other HealthBench variants. That benchmark tests rubric coverage in a different domain. For this API, the combination of low price and strict schemas makes Luna a good first choice for concise, bounded analyses. [Luna model reference](https://developers.openai.com/api/docs/models/gpt-6-luna) · [OpenAI evaluation](https://deploymentsafety.openai.com/gpt-6-astra#table-29-healthbench-evaluations-reported-as-length-adjusted-score-unadjusted-mean-response-length-in-characters-higher-is-better)
- **GPT-6.1 Terra** is positioned as a fast model for reasoning and writing. OpenAI reports better MMMU-Pro performance than GPT-5.6 Terra at each reasoning setting, which measures visual reasoning. Terra is a practical higher-cost option to evaluate when a site's service descriptions or audience signals are ambiguous. Both OpenAI models support the same request format used by this app. [Terra model reference](https://developers.openai.com/api/docs/models/gpt-6.1-terra) · [OpenAI evaluation](https://openai.com/index/introducing-gpt-6-1-terra/)
- **Gemini 3.1 Flash-Lite** is designed for high-volume, low-latency work. Google's model card reports 363 output tokens per second and a 43.3% SimpleQA Verified result for the published configuration. It is a credible candidate for extracted-text analysis when using the Gemini API. [Gemini model reference](https://aistudio.google.com/docs/models/gemini-3.1-flash-lite) · [DeepMind model card](https://deepmind.google/models/model-cards/gemini-3-1-flash-lite/)
- **Claude Haiku 5.5** is the fastest model in Anthropic's published comparison of its current lineup. Anthropic reports 85% on GPQA Diamond at default effort, a measure of graduate-level question answering. Its extraction focus and matching short-prompt price make it a candidate for a future cross-provider adapter. [Haiku model reference](https://platform.claude.com/docs/en/models/haiku-5-5/overview) · [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) · [Anthropic evaluation](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence)

The published figures cover different tasks and configurations. A representative site corpus would be needed to compare service attribution, schema acceptance, and recommendation quality for this API. The Google throughput figure measures generation speed under its benchmark conditions. The API's latency is currently unmeasured with live model traffic.

## Recommendation and operating estimate

**Primary** — `gpt-6-luna` at **$0.00150** per sample analysis. Use reasoning effort `none` and one combined structured call.

**Fallback** — `gpt-6.1-terra` at **$0.01500** per sample analysis. Set `OPENAI_MODEL=gpt-6.1-terra` and restart the service to switch. Switching is manual to preserve predictable costs and surface a genuine upstream failure.

For planning, budget roughly **15–45 seconds** end to end for a responsive site and a full structured answer. This is an engineering estimate. The default service allows up to 15 seconds for the entire website stage and 60 seconds for the provider call. Page count, output length, provider queueing, network path, and cold starts will affect latency. Measure median and p95 from real requests before promising a latency target.

The app removes boilerplate and duplicates, caps the extracted JSON, makes one provider request, and limits output to 4,500 tokens. Logs record token counts and wall time when available. An optional bounded TTL cache keyed by normalized content, model, and prompt version could reduce repeat spend without a database. Keep schema and prompt prefixes stable to improve provider-side cache reuse.
