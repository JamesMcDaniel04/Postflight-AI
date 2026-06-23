FROM python:3.12-slim

# Ascent's live-user evaluator drives a headless browser, so the image ships
# Playwright + Chromium. anthropic is pulled in via the [live] extra.
WORKDIR /app
COPY pyproject.toml README.md ./
COPY ascent ./ascent
# Install the package with the live extra, then Chromium + its OS dependencies
# (playwright install reads the browser version from the installed package).
RUN pip install --no-cache-dir ".[live]" \
    && playwright install --with-deps chromium

WORKDIR /github/workspace
ENTRYPOINT ["ascent", "ci"]
