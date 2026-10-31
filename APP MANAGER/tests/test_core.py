import unittest
from io import BytesIO

from PIL import Image

from fut7.logic import calculate_attributes, overall_from_attributes
from fut7.models import PlayerStats, User
from fut7.registration import (
    MAX_TEAM_LOGO_BYTES,
    logo_bytes_from_data,
    logo_data_from_upload,
    valid_email_address,
)
from fut7.security import (
    hash_password,
    is_valid_invite_pin,
    normalize_team_name,
    verify_password,
)


class RegistrationTests(unittest.TestCase):
    def test_validates_email_structure(self):
        self.assertTrue(valid_email_address("jogador.silva+fut7@exemplo.com"))
        for email in (
            "",
            "jogador@@exemplo.com",
            "jogador@exemplo",
            ".jogador@exemplo.com",
            "jogador..silva@exemplo.com",
            "jogador@-exemplo.com",
            " jogador@exemplo.com",
        ):
            with self.subTest(email=email):
                self.assertFalse(valid_email_address(email))

    def test_validates_and_round_trips_team_logo(self):
        image_buffer = BytesIO()
        Image.new("RGB", (4, 4), color="green").save(image_buffer, format="PNG")
        image_data = image_buffer.getvalue()

        class Upload:
            def getvalue(self):
                return image_data

        encoded = logo_data_from_upload(Upload())
        if encoded is None:
            self.fail("A valid image should produce a data URL.")
        self.assertTrue(encoded.startswith("data:image/png;base64,"))
        self.assertEqual(logo_bytes_from_data(encoded), image_data)
        self.assertIsNone(logo_data_from_upload(None))

    def test_rejects_empty_oversized_and_invalid_images(self):
        class Upload:
            def __init__(self, content):
                self.content = content

            def getvalue(self):
                return self.content

        for content, message in (
            (b"", "vazio"),
            (b"x" * (MAX_TEAM_LOGO_BYTES + 1), "2 MB"),
            (b"not an image", "PNG, JPEG ou WebP"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    logo_data_from_upload(Upload(content))


class SecurityAndLogicTests(unittest.TestCase):
    def test_password_hashing_and_invite_pin_rules(self):
        password_hash = hash_password("senha-segura-123")
        self.assertNotEqual(password_hash, hash_password("senha-segura-123"))
        self.assertTrue(verify_password("senha-segura-123", password_hash))
        self.assertFalse(verify_password("senha-incorreta", password_hash))
        self.assertFalse(verify_password("senha", "malformed"))

        self.assertTrue(is_valid_invite_pin("012345"))
        self.assertTrue(is_valid_invite_pin("123456789012"))
        self.assertFalse(is_valid_invite_pin("12345"))
        self.assertFalse(is_valid_invite_pin("１２３４５６"))

    def test_normalizes_team_names(self):
        self.assertEqual(normalize_team_name("  Águias   do FUT7 "), "aguias do fut7")

    def test_calculates_bounded_player_attributes(self):
        player = User(name="Atleta", height_cm=170, weight_kg=70)
        stats = [
            PlayerStats(
                goals=2,
                assists=1,
                shots_on_target=3,
                tackles=4,
                yellow_cards=0,
                red_cards=0,
                coach_rating=4.0,
            )
        ]

        attributes = calculate_attributes(player, stats, [])

        self.assertEqual(len(attributes), 6)
        self.assertTrue(all(0 <= score <= 100 for score in attributes.values()))
        self.assertEqual(overall_from_attributes(attributes), round(sum(attributes.values()) / 6))


if __name__ == "__main__":
    unittest.main()
