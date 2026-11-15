# Respaldos y restauración (E1C-140). Misma versión de PostgreSQL que deploy/postgres.Dockerfile:
# pg_dump y pg_restore tienen que coincidir con el servidor.
FROM postgres:16.15-bookworm

COPY deploy/respaldos.sh /usr/local/bin/respaldos
# Sin CRLF aunque el equipo que construye tenga finales de línea de Windows.
RUN sed -i 's/\r$//' /usr/local/bin/respaldos \
    && chmod 755 /usr/local/bin/respaldos \
    && mkdir -p /respaldos /datos /media /destino/datos /destino/media \
    && chown postgres:postgres /respaldos \
    && chown 10001:10001 /datos /media /destino/datos /destino/media

# Un volumen nuevo hereda el propietario de la carpeta del primer contenedor que lo monta. Si ese
# es respaldos o restaurador, datos y media tienen que quedar del usuario de la aplicación
# (10001, como en el Dockerfile del backend): si no, el backend no podría escribir en ellos.
USER postgres
ENTRYPOINT ["respaldos"]
CMD ["programar"]
