# backend/Dockerfile
FROM python:3.12-slim

# Native libs needed by Pillow / torchvision
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install base deps from requirements (NO torch/torchvision here)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install CPU-only PyTorch wheels (pair versions that match)
# If build fails due to availability, bump to 2.5.1 / 0.20.1.
RUN pip install --index-url https://download.pytorch.org/whl/cpu \
    torch==2.4.1 torchvision==0.19.1 \
    --extra-index-url https://pypi.org/simple

# Copy the rest of the backend (includes AIBE Parts list.xlsx and images/)
COPY . .

# Build the SQLite DB and image embeddings at build time
RUN python load_parts.py
RUN python generate_embeddings.py

# Runtime env
ENV PORT=8080 \
    EMBED_DIR=embeddings \
    PARTS_DB_PATH=parts.db \
    CORS_ORIGINS=https://REPLACE_WITH_NETLIFY_DOMAIN

EXPOSE 8080

CMD ["python","-m","uvicorn","main:app","--host","0.0.0.0","--port","8080"]
