import base64
import importlib.util
import secrets
import unittest
from pathlib import Path


PII_PATH = Path(__file__).resolve().parents[1] / "flaskr" / "pii.py"
SPEC = importlib.util.spec_from_file_location("sarkari_pii", PII_PATH)
pii = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pii)


class PersonalDataEncryptionTests(unittest.TestCase):
    def setUp(self):
        self.key = secrets.token_bytes(32)

    def test_round_trip_and_bound_fields(self):
        value = "1990-02-03"
        encrypted = pii.encrypt_value(value, "dob", 42, self.key)
        self.assertEqual(pii.decrypt_value(encrypted, "dob", 42, self.key), value)
        with self.assertRaises(pii.SensitiveDataError):
            pii.decrypt_value(encrypted, "income", 42, self.key)

    def test_each_encryption_uses_a_distinct_nonce(self):
        first = pii.encrypt_value("same", "name", 8, self.key)
        second = pii.encrypt_value("same", "name", 8, self.key)
        self.assertNotEqual(first, second)

    def test_tampered_ciphertext_is_rejected(self):
        encrypted = pii.encrypt_value("secret", "caste", 7, self.key)
        encoded = encrypted[len(pii.ENCRYPTED_PREFIX):]
        payload = bytearray(base64.b64decode(encoded, altchars=b"-_"))
        payload[-1] ^= 1
        tampered = pii.ENCRYPTED_PREFIX + base64.urlsafe_b64encode(payload).decode("ascii")
        with self.assertRaises(pii.SensitiveDataError):
            pii.decrypt_value(tampered, "caste", 7, self.key)
        with self.assertRaises(pii.SensitiveDataError):
            pii.encrypt_legacy_profile({"caste": tampered}, 7, self.key)

    def test_migration_transform_is_idempotent_and_preserves_values(self):
        legacy = {
            "name": "Example Person", "dob": "1990-02-03", "income": 123456,
            "aadhar": "123456789012", "pan": "ABCDE1234F", "caste": "OBC",
        }
        first = pii.encrypt_legacy_profile(legacy, 12, self.key)
        migrated = {**legacy, **first}
        self.assertEqual(pii.encrypt_legacy_profile(migrated, 12, self.key), {})
        restored = pii.decrypt_profile(migrated, 12, self.key)
        for field, value in legacy.items():
            self.assertEqual(restored[field], str(value))

    def test_identifier_mask_keeps_only_last_four_characters(self):
        self.assertEqual(pii.mask_identifier("123456789012"), "********9012")
        self.assertEqual(pii.mask_identifier("ABCDE1234F"), "******234F")

    def test_decrypted_profile_retains_eligibility_inputs(self):
        values = {
            "name": "Example Person", "age": 36, "dob": "1990-02-03",
            "gender": "Female", "income": 250000, "caste": "OBC",
            "states": "Delhi", "occupation": "Farmer",
        }
        encrypted = pii.encrypt_profile(values, 42, self.key)
        restored = pii.decrypt_profile(encrypted, 42, self.key, pii.ELIGIBILITY_FIELDS)
        self.assertEqual(restored["name"], values["name"])
        self.assertEqual(int(restored["age"]), values["age"])
        self.assertEqual(int(restored["income"]), values["income"])
        self.assertEqual(restored["caste"], values["caste"])

    def test_key_must_decode_to_32_bytes(self):
        self.assertEqual(len(pii.decode_key(base64.b64encode(self.key).decode("ascii"))), 32)
        with self.assertRaises(pii.SensitiveDataError):
            pii.decode_key(base64.b64encode(b"short").decode("ascii"))

    def test_email_encryption_and_keyed_lookup(self):
        encrypted = pii.encrypt_email("User@example.com", "sample-user", self.key)
        self.assertEqual(pii.decrypt_email(encrypted, "sample-user", self.key), "User@example.com")
        self.assertEqual(pii.email_lookup("User@example.com", self.key),
                         pii.email_lookup(" user@EXAMPLE.com ", self.key))
        self.assertEqual(pii.mask_email("user@example.com"), "u***@example.com")


if __name__ == "__main__":
    unittest.main()
