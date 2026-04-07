# Nodalia Wasabi Backups

Integracion personalizada de Home Assistant para guardar backups en Wasabi con una experiencia mas limpia para clientes finales.

La integracion registra un `backup agent` dentro de Home Assistant y envia cada copia al bucket configurado en Wasabi usando la API S3. Esta version esta pensada para despliegues gestionados por Nodalia:

- endpoint Wasabi generado automaticamente a partir de la region
- separacion por cliente o instalacion usando un prefijo limpio y estable
- cifrado en reposo por objeto con `AES256`
- validacion de permisos de lectura, escritura y borrado durante la configuracion

## Flujo de almacenamiento

Cada instalacion queda aislada en su propio prefijo:

```text
<bucket>/
  homeassistant/
    <cliente-slug>/
      backups/
        <backup-id>.tar
        <backup-id>.metadata.json
```

Si necesitas otra jerarquia, el campo `Root path` permite cambiar `homeassistant/` por otra carpeta base.

## Configuracion

Desde `Settings > Devices & Services > Add Integration`, busca `Nodalia Wasabi Backups` y completa:

- `Installation name`: carpeta principal del cliente
- `Additional house`: subcarpeta opcional para una segunda vivienda, oficina o instalacion extra
- `Bucket`: bucket de Wasabi, predefinido como `nodalia-backups` aunque editable
- `Access Key`: credencial del cliente
- `Secret Key`: secreto de la credencial
- `Region`: region de Wasabi, por defecto `eu-west-2`
- `Root path`: carpeta base opcional, por defecto `homeassistant`

La integracion genera automaticamente el endpoint `https://s3.<region>.wasabisys.com` y el prefijo final `<root_path>/<installation_slug>[/<additional_house_slug>]`.

Si un cliente tiene varias instalaciones, usa `Additional house` para separarlas. Por ejemplo:

- `Installation name = cliente`, `Additional house = casa1` -> `homeassistant/cliente/casa1`
- `Installation name = cliente`, `Additional house = casa2` -> `homeassistant/cliente/casa2`

Tambien se sigue admitiendo `/` dentro de `Installation name` si necesitas una estructura mas avanzada.

## Recomendacion de seguridad

Lo ideal es entregar a cada cliente una credencial distinta, limitada solo a su prefijo. Un ejemplo de politica compatible con S3 seria:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListOwnPrefix",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": ["arn:aws:s3:::TU_BUCKET"],
      "Condition": {
        "StringLike": {
          "s3:prefix": ["homeassistant/cliente-demo/*"]
        }
      }
    },
    {
      "Sid": "AccessOwnObjects",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:AbortMultipartUpload",
        "s3:ListMultipartUploadParts"
      ],
      "Resource": ["arn:aws:s3:::TU_BUCKET/homeassistant/cliente-demo/*"]
    }
  ]
}
```

Sustituye `cliente-demo` por el slug real generado a partir de `Installation name`.

## Estructura del proyecto

- `custom_components/nodalia_backups_s3/`: integracion de Home Assistant
- `tests/`: base de pruebas unitarias para helpers, config flow y agente de backup

## Estado actual

Esta primera version deja lista la integracion base con branding propio y especializacion en Wasabi. Si quieres, el siguiente paso natural es convertir el bucket en un valor fijo de tu despliegue para que el cliente no tenga que introducirlo manualmente.
