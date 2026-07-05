FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm
RUN useradd --create-home --uid 1000 plextrakt \
    && mkdir /config && chown plextrakt:plextrakt /config
WORKDIR /app
COPY --from=builder --chown=plextrakt:plextrakt /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" STATE_DIR=/config
USER plextrakt
VOLUME /config
ENTRYPOINT ["plextrakt"]
CMD ["run"]
