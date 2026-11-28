# Hardened rootless container image for optional Docker-backed sandbox execution.
# Note: Containers alone are not a perfect security boundary; combine with
# --network=none, --read-only, --cap-drop=ALL, --security-opt=no-new-privileges,
# --pids-limit, --memory, and --cpus when running untrusted code.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONNOUSERSITE=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 sandbox \
    && useradd --uid 10001 --gid 10001 --shell /sbin/nologin --create-home sandbox

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY config /app/config
COPY data /app/data
COPY scripts /app/scripts

RUN pip install --no-deps . \
    && chown -R sandbox:sandbox /app

USER 10001:10001

ENTRYPOINT ["python", "-m", "strategy_sandbox.cli"]
CMD ["--help"]
