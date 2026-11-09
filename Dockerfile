# syntax=docker/dockerfile:1

# =============================================================================
# Stage 1 — builder
# Tugasnya hanya menyiapkan virtualenv berisi dependency. Semua alat build dan
# cache pip tetap tinggal di stage ini dan tidak ikut ke image akhir.
# =============================================================================
FROM python:3.12.11-slim-bookworm AS builder

# Output Python langsung dikirim ke log container, tanpa buffer.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# requirements.txt disalin lebih dulu, baru kode. Dengan urutan ini, layer
# "pip install" tetap memakai cache selama dependency tidak berubah.
COPY requirements.txt ./

# Virtualenv diletakkan di /opt/venv agar mudah disalin ke stage runtime.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip==24.3.1 \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# =============================================================================
# Stage 2 — runtime
# Image akhir hanya berisi Python, virtualenv hasil builder, dan kode aplikasi.
# =============================================================================
FROM python:3.12.11-slim-bookworm AS runtime

# PATH diarahkan ke virtualenv supaya "uvicorn" bisa dipanggil langsung.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Jalankan sebagai user non-root: bila aplikasi dibobol, haknya tetap terbatas.
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

WORKDIR /app

# Hanya virtualenv dari builder yang dibawa masuk.
COPY --from=builder /opt/venv /opt/venv

# COPY, bukan ADD: COPY hanya menyalin file dari context. ADD dapat mengekstrak
# arsip dan mengunduh URL secara otomatis — fitur yang tidak kita butuhkan dan
# lebih sulit diaudit. --chown membuat file tetap bisa dibaca user "app".
COPY --chown=app:app app ./app

# Ganti ke user non-root sebelum menjalankan aplikasi.
USER app

# Dokumentasi port; pemetaan ke host diatur di docker-compose.yml.
EXPOSE 8000

# Exec form: uvicorn menjadi PID 1 sehingga menerima sinyal stop dari Docker.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
