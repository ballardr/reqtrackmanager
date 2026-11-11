"""
Module: services.password_policy

The rule for a newly chosen password (access control Known Gap 2).

Responsibilities:
- Enforce the length range: at least `MIN_PASSWORD_LENGTH` characters and at most 72 bytes (bcrypt reads no more, so
  a longer password would be silently shortened and two different long passwords could be the same credential).
- Refuse a password on a built-in list of the most commonly used ones, one made of a single repeated character, and
  one equal to the account's own email address or its local part.

Design decisions:
- Applied only where a password is chosen (sign-up, change, reset, administrator-created account), never on sign-in,
  so an existing password that predates the rule keeps working until it is next changed.
- A built-in list and no external lookup: nothing about a password or its hash leaves the deployment.

External dependencies: none.
"""

from __future__ import annotations

from app.security import MIN_PASSWORD_LENGTH

#: bcrypt reads at most this many bytes of a password.
MAX_PASSWORD_BYTES = 72

_COMMON = frozenset(
    """
    password password1 password12 password123 password1234 passw0rd p@ssw0rd p@ssword pa$$word letmein letmein1
    welcome welcome1 welcome123 admin admin123 administrator changeme changeme123 qwerty qwerty123 qwertyuiop
    qwerty12345 asdfghjkl zxcvbnm 12345678 123456789 1234567890 12345678910 11111111 00000000 87654321 123123123
    1q2w3e4r 1q2w3e4r5t 1qaz2wsx iloveyou iloveyou1 monkey monkey123 dragon dragon123 football football1 baseball
    master master123 sunshine princess superman batman trustno1 abc12345 abcd1234 abcdefgh abcdefg1 secret secret123
    login login123 default default123 test1234 testtest test1234567 guest guest123 user user1234 root root1234
    starwars whatever freedom shadow shadow1 michael jordan23 liverpool chelsea arsenal hunter hello123 hellohello
    summer2020 summer2021 summer2022 summer2023 summer2024 winter2020 winter2021 winter2022 winter2023 winter2024
    spring2023 spring2024 autumn2023 autumn2024 january1 february1 monday123 november1 computer computer1 internet
    google google123 microsoft office365 windows windows10 ubuntu linux123 spiderman pokemon mustang cheese
    """.split()
)


def password_problem(password: str, email: str | None = None) -> str | None:
    """Why `password` may not be chosen, or `None` when it may.

    Args:
        password: The candidate password.
        email: The account's email address, when known.

    Returns:
        A message for the person choosing it, or `None`.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return f"Password must be at most {MAX_PASSWORD_BYTES} bytes."
    lowered = password.lower()
    if lowered in _COMMON or len(set(lowered)) == 1:
        return "This password is too common. Choose a different one."
    if email and lowered in {email.lower(), email.lower().split("@")[0]}:
        return "Password must not be the email address."
    return None


def validate_new_password(password: str, email: str | None = None) -> str:
    """Pydantic-validator form of `password_problem`: returns the password, or raises `ValueError`.

    Raises:
        ValueError: With the message from `password_problem`.
    """
    problem = password_problem(password, email)
    if problem:
        raise ValueError(problem)
    return password
