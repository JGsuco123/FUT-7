from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image, UnidentifiedImageError

MAX_TEAM_LOGO_BYTES = 2 * 1024 * 1024


def valid_email_address(email: str) -> bool:
    if len(email) > 254 or email.count("@") != 1 or any(char.isspace() for char in email):
        return False

    local, domain = email.split("@")
    if (
        not local
        or len(local) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
    ):
        return False

    allowed_local_symbols = ".!#$%&'*+-/=?^_`{|}~"
    if any(not (char.isalnum() or char in allowed_local_symbols) for char in local):
        return False

    labels = domain.split(".")
    return len(labels) >= 2 and all(
        label
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and all(char.isalnum() or char == "-" for char in label)
        for label in labels
    )


def logo_data_from_upload(uploaded_file) -> str | None:
    if uploaded_file is None:
        return None
    content = uploaded_file.getvalue()
    if not content:
        raise ValueError("O arquivo do escudo está vazio.")
    if len(content) > MAX_TEAM_LOGO_BYTES:
        raise ValueError("O escudo deve ter no máximo 2 MB.")

    try:
        with Image.open(BytesIO(content)) as image:
            image_format = image.format
            if image.width > 4096 or image.height > 4096:
                raise ValueError("A imagem do escudo não pode exceder 4096 × 4096 pixels.")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError("Envie um arquivo de imagem válido em PNG, JPEG ou WebP.") from error

    media_types = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
    if image_format is None:
        raise ValueError("Envie um escudo válido em PNG, JPEG ou WebP.")
    media_type = media_types.get(image_format)
    if media_type is None:
        raise ValueError("Envie um escudo válido em PNG, JPEG ou WebP.")
    return f"data:{media_type};base64,{base64.b64encode(content).decode('ascii')}"


def logo_bytes_from_data(logo_data: str | None) -> bytes | None:
    if not logo_data:
        return None
    media_type, separator, encoded = logo_data.partition(";base64,")
    if not separator or media_type not in {"data:image/png", "data:image/jpeg", "data:image/webp"}:
        raise ValueError("O escudo salvo do time possui um formato inválido.")
    return base64.b64decode(encoded, validate=True)
