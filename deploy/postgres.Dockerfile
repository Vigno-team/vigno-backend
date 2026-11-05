FROM postgres:16.15-bookworm

# El volumen nuevo hereda el propietario de la imagen. El entrypoint puede
# ejecutar initdb como postgres sin arrancar como root ni hacer chown en runtime.
USER postgres
