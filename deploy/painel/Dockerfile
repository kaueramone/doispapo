FROM docker.io/python:3.12-alpine
RUN pip install --no-cache-dir pymongo==4.10.1
COPY app.py painel.html painel.js simbolo.png /app/
WORKDIR /app
EXPOSE 8700
CMD ["python", "-u", "/app/app.py"]
