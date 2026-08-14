from app.core.security import get_password_hash, verify_password

LEGACY_PASSLIB_ARGON2_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$WiuFsBaC0Ppf6/0/51wLwQ"
    "$w5RhR+WoE4NaGmW2hrnPOX2+QwqKnUxbJklvs8WRAds"
)


def test_hash_and_verify_password():
    hashed_password = get_password_hash("secure_password")

    assert hashed_password.startswith("$argon2id$")
    assert verify_password("secure_password", hashed_password) is True
    assert verify_password("wrong_password", hashed_password) is False


def test_verify_legacy_passlib_argon2_hash():
    assert verify_password("legacy_password", LEGACY_PASSLIB_ARGON2_HASH) is True
