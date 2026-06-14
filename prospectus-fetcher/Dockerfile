FROM python:3.12-slim

WORKDIR /app

# Install package in non-editable mode from the local source tree.
# Dependencies are installed first so the layer is cached independently
# of source changes.
COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# SEC_USER_AGENT must be supplied at runtime via -e or the orchestrator's
# secret injection — never hardcoded here.
ENV SEC_USER_AGENT=""

ENTRYPOINT ["prospectus-fetch"]
CMD ["--help"]
