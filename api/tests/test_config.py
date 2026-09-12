"""Database URL normalisation.

Every case here is a real connection string shape someone will paste in, and
every one of them fails at first connect rather than at import — which is the
worst time to find out.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from app.config import normalize_database_url

NEON = (
    "postgresql://user:pw@ep-twilight-math-b3jfqk4u-pooler.c-4.ap-southeast-1"
    ".aws.neon.tech/scholarcompass?sslmode=require&channel_binding=require"
)


def test_neon_url_gets_the_asyncpg_driver():
    assert normalize_database_url(NEON).startswith("postgresql+asyncpg://")


def test_libpq_only_params_are_stripped():
    """asyncpg raises TypeError on sslmode/channel_binding."""
    q = parse_qs(urlsplit(normalize_database_url(NEON)).query)
    assert "sslmode" not in q
    assert "channel_binding" not in q


def test_tls_is_preserved_not_dropped():
    """Stripping sslmode must not silently downgrade the connection."""
    q = parse_qs(urlsplit(normalize_database_url(NEON)).query)
    assert q.get("ssl") == ["require"]


def test_credentials_and_database_survive():
    out = normalize_database_url(NEON)
    assert "user:pw@" in out
    assert "/scholarcompass" in out
    assert "ep-twilight-math-b3jfqk4u-pooler" in out


def test_already_correct_url_is_left_alone():
    good = "postgresql+asyncpg://u:p@host:5432/db"
    assert normalize_database_url(good) == good


def test_postgres_scheme_alias_is_upgraded():
    """Heroku-style postgres:// is still common in pasted configs."""
    assert normalize_database_url("postgres://u:p@h/db").startswith("postgresql+asyncpg://")


def test_local_url_without_params_is_untouched():
    local = "postgresql+asyncpg://postgres:postgres@localhost:5432/scholarcompass"
    assert normalize_database_url(local) == local


def test_unrelated_params_are_kept():
    url = NEON + "&application_name=scholarcompass"
    q = parse_qs(urlsplit(normalize_database_url(url)).query)
    assert q.get("application_name") == ["scholarcompass"]


def test_sslmode_disable_does_not_add_ssl():
    url = "postgresql://u:p@localhost/db?sslmode=disable"
    q = parse_qs(urlsplit(normalize_database_url(url)).query)
    assert "ssl" not in q


def test_empty_url_does_not_raise():
    assert normalize_database_url("") == ""
