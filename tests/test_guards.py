import pandas as pd
import pytest

from fsq_agent.sql import guards


def test_select_passes():
    guards.check("SELECT * FROM ev_sales_daily")


def test_cte_passes():
    guards.check("WITH t AS (SELECT 1) SELECT * FROM t")


@pytest.mark.parametrize("sql", [
    "DROP TABLE ev_sales_daily",
    "DELETE FROM re_transactions",
    "SELECT 1; DROP TABLE x",
    "UPDATE ev_sales_daily SET units_sold = 0",
])
def test_dangerous_sql_rejected(sql):
    with pytest.raises(guards.UnsafeSQLError):
        guards.check(sql)


def test_row_limit_wraps_query():
    wrapped = guards.with_row_limit("SELECT * FROM t LIMIT 999999")
    assert wrapped.upper().startswith("SELECT * FROM (")
    assert "LIMIT 500" in wrapped


@pytest.mark.parametrize("sql", [
    'SELECT "PasswordHash" FROM "Users"',
    'SELECT "Username", "Email" FROM "Users"',
    'SELECT * FROM "Users" WHERE "WalletAddress" = \'0xabc\'',
    'SELECT "NonceValue" FROM "Nonces"',
    "select passwordhash from users",              # unquoted, lower case
    'SELECT u."Email" FROM "Users" u JOIN "Roles" r ON r."Id" = u."Id"',
])
def test_sensitive_columns_rejected(sql):
    with pytest.raises(guards.UnsafeSQLError, match="restricted column"):
        guards.check(sql)


def test_sensitive_rejection_names_the_column():
    """The repair loop needs to know which column to drop."""
    with pytest.raises(guards.UnsafeSQLError, match="passwordhash"):
        guards.check('SELECT "PasswordHash" FROM "Users"')


@pytest.mark.parametrize("sql", [
    'SELECT "Username", "IsVerified" FROM "Users"',
    'SELECT count(*) FROM "EmailTemplates"',        # substring, not whole word
    'SELECT "AuthProvider" FROM "Users"',
])
def test_non_sensitive_columns_pass(sql):
    guards.check(sql)


# --- T1.3 / T1.5: result-set filtering catches SELECT * -----------------------

def test_select_star_result_is_stripped():
    """The query text names no column, so only the result set gives it away."""
    df = pd.DataFrame(
        {"Id": [1], "WalletAddress": ["0xabc"], "NonceValue": ["tok"], "IsUsed": [False]}
    )
    out, withheld = guards.strip_sensitive_columns(df)
    assert list(out.columns) == ["Id", "IsUsed"]
    assert sorted(withheld) == ["NonceValue", "WalletAddress"]


def test_clean_result_passes_through_untouched():
    df = pd.DataFrame({"Id": [1], "Username": ["ann"]})
    out, withheld = guards.strip_sensitive_columns(df)
    assert withheld == []
    assert out.equals(df)


def test_result_filter_is_case_insensitive():
    df = pd.DataFrame({"passwordhash": ["x"], "PASSWORDHASH": ["y"], "Id": [1]})
    out, withheld = guards.strip_sensitive_columns(df)
    assert list(out.columns) == ["Id"]
    assert len(withheld) == 2


def test_result_filter_keeps_rows():
    """Only columns are dropped — row count must be untouched."""
    df = pd.DataFrame({"Id": [1, 2, 3], "Email": ["a", "b", "c"]})
    out, _ = guards.strip_sensitive_columns(df)
    assert len(out) == 3


# --- T1.2 backstop: schema-qualified names bypass the search_path -------------

@pytest.mark.parametrize("sql", [
    'SELECT * FROM public."Users"',
    "SELECT count(*) FROM auth.users",
    "SELECT * FROM storage.objects",
    "SELECT * FROM vault.secrets",
    'SELECT * FROM PUBLIC."Users"',                 # case-insensitive
    'SELECT * FROM public . "Users"',               # whitespace around the dot
])
def test_schema_qualified_access_rejected(sql):
    with pytest.raises(guards.UnsafeSQLError, match="schema"):
        guards.check(sql)


@pytest.mark.parametrize("sql", [
    'SELECT count(*) FROM "Users"',                 # the most common shape
    'SELECT u."Id" FROM "Users" u',                 # table alias, not a schema
    'SELECT "Id" FROM "Users" WHERE "Id" IN (SELECT "UserId" FROM "UserRoles")',
])
def test_unqualified_queries_still_pass(sql):
    guards.check(sql)
