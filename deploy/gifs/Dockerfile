FROM docker.io/python:3.12-alpine
RUN pip install --no-cache-dir pymongo==4.10.1
COPY app.py /app.py
EXPOSE 8602
CMD ["python", "-u", "/app.py"]
