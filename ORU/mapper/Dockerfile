FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir hl7 httpx

COPY main.py mapper.py terminology.py ./

CMD ["python", "main.py"]
