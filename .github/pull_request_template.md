## Ticket

E1C-

## Que hace este PR

## Contexto para el equipo

**Antes / ahora:** qué hacía este código y qué hace después del cambio.

**Lo que saqué o junté:** y por qué no rompe nada.

**Cómo lo comprobé:** por ejemplo, el JSON de referencia sale igual.

**Si alguien tiene que cambiar esto después:** dónde mirar primero (archivo y función).

**Ojo con:** algo que no quedó del todo claro, un caso raro o una duda pendiente.

## Como probarlo

```bash
docker compose up
# pasos para verificar el cambio
```

## Definition of Done

- [ ] El ticket de Jira esta enlazado y en estado correcto
- [ ] Tests incluidos y pasando en local
- [ ] Migraciones incluidas si el PR toca el esquema de la base
- [ ] El proyecto levanta desde cero con `docker compose up`
- [ ] No hay archivos de datos del cliente ni `.env` en el diff
- [ ] Documentacion o README actualizados si aplica

## Notas para quien revisa
