FROM python:3.13-slim-bookworm
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates unixodbc libgssapi-krb5-2 \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb -o /tmp/microsoft.deb \
    && dpkg -i /tmp/microsoft.deb \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/* /tmp/microsoft.deb
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home wol \
    && mkdir /state && chown wol:wol /state
COPY app.py alexa_wol.py alexa_worker.py production_config.py migrate_db.py ./
COPY templates ./templates
ENV PYTHONUNBUFFERED=1 WOL_STATE_DIR=/state HOST=0.0.0.0 PORT=5000
USER wol
EXPOSE 5000
CMD ["python", "app.py"]
