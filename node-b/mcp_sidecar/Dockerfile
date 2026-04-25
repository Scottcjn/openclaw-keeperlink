FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir aiohttp==3.10.11
COPY router_and_echo.py /app/
EXPOSE 9003 9004
CMD ["python", "-u", "/app/router_and_echo.py"]
