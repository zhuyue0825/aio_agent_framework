FROM postgres:17-alpine

COPY postgres-backup.sh /usr/local/bin/postgres-backup
RUN chmod 0555 /usr/local/bin/postgres-backup \
    && install -d -o postgres -g postgres -m 0700 /backups

USER postgres
ENTRYPOINT ["/usr/local/bin/postgres-backup"]
