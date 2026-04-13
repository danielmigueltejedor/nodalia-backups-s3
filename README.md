# 📦 Nodalia Wasabi Backups

![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5?logo=home-assistant)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-stable-success.svg)
![GitHub](https://img.shields.io/badge/hosted%20on-GitHub-black?logo=github)

Integración personalizada de Home Assistant para guardar backups en Wasabi con una experiencia más limpia para clientes finales.  
Especializada en despliegues gestionados por Nodalia.

> 🟡 Proyecto no afiliado a Home Assistant ni a Wasabi.  
> Uso personal y educativo.

---

## ✨ Características

- Endpoint Wasabi generado automáticamente a partir de la región
- Separación por cliente o instalación usando un prefijo limpio y estable
- Cifrado en reposo por objeto con `AES256`
- Validación de permisos de lectura, escritura y borrado durante la configuración
- Soporte para múltiples contratos por cliente

---

## 🧩 Instalación

### 🔹 Opción 1 — HACS (Recomendada)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=danielmigueltejedor&repository=nodalia-backups-s3&category=Integration)

---

## ⚙️ Configuración

Desde `Ajustes > Dispositivos e Integraciones > Añadir integración`, busca `Nodalia Wasabi Backups` y completa:

- `Installation name`: carpeta principal del cliente
- `Additional house`: subcarpeta opcional para una segunda vivienda, oficina o instalación extra
- `Bucket`: bucket de Wasabi, predefinido como `nodalia-backups` aunque editable
- `Access Key`: credencial del cliente
- `Secret Key`: secreto de la credencial
- `Region`: región de Wasabi, por defecto `eu-west-2`
- `Root path`: carpeta base opcional, por defecto `homeassistant`

La integración genera automáticamente el endpoint `https://s3.<region>.wasabisys.com` y el prefijo final `<root_path>/<installation_slug>[/<additional_house_slug>]`.

Si un cliente tiene varias instalaciones, usa `Additional house` para separarlas. Por ejemplo:

- `Installation name = cliente`, `Additional house = casa1` -> `homeassistant/cliente/casa1`
- `Installation name = cliente`, `Additional house = casa2` -> `homeassistant/cliente/casa2`

También se sigue admitiendo `/` dentro de `Installation name` si necesitas una estructura más avanzada.

---

## 🧠 Detalles técnicos

### Flujo de almacenamiento

Cada instalación queda aislada en su propio prefijo:

```text
<bucket>/
  homeassistant/
    <cliente-slug>/
      backups/
        <backup-id>.tar
        <backup-id>.metadata.json
```

Si necesitas otra jerarquía, el campo `Root path` permite cambiar `homeassistant/` por otra carpeta base.

### Recomendación de seguridad

Lo ideal es entregar a cada cliente una credencial distinta, limitada solo a su prefijo. Un ejemplo de política compatible con S3 sería:

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

---

## 📁 Estructura del proyecto

- `custom_components/nodalia_backups_s3/`: integración de Home Assistant
- `tests/`: base de pruebas unitarias para helpers, config flow y agente de backup

---

## 🧑‍💻 Autor

- **[@danielmigueltejedor](https://github.com/danielmigueltejedor)**  
- Repositorio: https://github.com/danielmigueltejedor/nodalia-backups-s3  
- Licencia: MIT

---

## ⚠️ Estado actual

Esta primera versión deja lista la integración base con branding propio y especialización en Wasabi. Si quieres, el siguiente paso natural es convertir el bucket en un valor fijo de tu despliegue para que el cliente no tenga que introducirlo manualmente.

---

## 💰 Donaciones

Si te gusta este proyecto y quieres apoyar su desarrollo, considera hacer una donación:

[![PayPal](https://img.shields.io/badge/Donate-PayPal-blue.svg)](https://paypal.me/DanielMiguelTejedor)
