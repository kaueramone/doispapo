#!/usr/bin/env bash
# Backup do Dois Papo: configuração, banco e arquivos enviados.
# Uso: ./backup.sh          (roda por cron, silencioso em caso de sucesso)
set -euo pipefail

RAIZ=/root/stoat
DEST=/root/backups
MANTER_DIAS=14
TS=$(date +%F-%H%M)
LOG=$DEST/backup.log

registra(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

cd "$RAIZ"
mkdir -p "$DEST"

# --- configuração e segredos (pequeno, sempre) -------------------------
tar czf "$DEST/config-$TS.tar.gz" \
  secrets.env Revolt.toml livekit.yml .env .env.web stoat.json \
  Caddyfile compose.override.yml 2>/dev/null
chmod 600 "$DEST/config-$TS.tar.gz"

# --- MongoDB ------------------------------------------------------------
docker compose exec -T database mongodump --archive --gzip \
  > "$DEST/mongo-$TS.gz"

# --- arquivos enviados (MinIO) -----------------------------------------
tar czf "$DEST/minio-$TS.tar.gz" data/minio 2>/dev/null

# --- verificação: um backup que não abre não é backup -------------------
erros=0
gzip -t "$DEST/mongo-$TS.gz"            || { registra "FALHA: mongo corrompido"; erros=1; }
tar tzf "$DEST/config-$TS.tar.gz" >/dev/null || { registra "FALHA: config corrompido"; erros=1; }
tar tzf "$DEST/minio-$TS.tar.gz"  >/dev/null || { registra "FALHA: minio corrompido"; erros=1; }

if [ "$erros" -ne 0 ]; then
  registra "backup $TS terminou COM ERROS"
  exit 1
fi

# --- expurgo dos antigos ------------------------------------------------
find "$DEST" -name 'config-*.tar.gz' -mtime +$MANTER_DIAS -delete
find "$DEST" -name 'mongo-*.gz'      -mtime +$MANTER_DIAS -delete
find "$DEST" -name 'minio-*.tar.gz'  -mtime +$MANTER_DIAS -delete

TAM=$(du -sh "$DEST" | cut -f1)
registra "backup $TS concluído e verificado (total em disco: $TAM)"
