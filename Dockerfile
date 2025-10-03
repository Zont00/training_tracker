FROM python:3.11-slim

# Evita cache e buffer
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Installiamo pacchetti base (per pandas, numpy, ecc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Installiamo le librerie Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamo tutto il progetto
COPY . .

# Comando di avvio
CMD ["python", "main.py"]
