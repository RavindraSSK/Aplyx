FROM python:3.11-slim

WORKDIR /srv/jobagent

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir -e .

COPY data ./data
COPY alembic.ini ./

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
