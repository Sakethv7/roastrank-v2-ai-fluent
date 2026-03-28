FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    poppler-utils \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces requires containers to run as user ID 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

EXPOSE 7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
