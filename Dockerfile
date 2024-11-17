FROM python:3.9-slim-buster

COPY . /app
WORKDIR /app

RUN pip install -r requirements.txt

ENTRYPOINT ["python", "/app/.github/scripts/spam_detector.py"] 
