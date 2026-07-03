"""
Generates human-friendly sequential identifiers (member numbers, account
numbers, loan numbers, journal entry numbers) with a random suffix to avoid
collisions under concurrent writes without needing a DB sequence lock.
"""
import random
import string
from datetime import datetime


def _suffix(n: int = 4) -> str:
    return "".join(random.choices(string.digits, k=n))


def generate_member_number() -> str:
    return f"MB{datetime.utcnow().strftime('%y%m')}{_suffix()}"


def generate_savings_account_number() -> str:
    return f"SV{datetime.utcnow().strftime('%y%m')}{_suffix(6)}"


def generate_loan_number() -> str:
    return f"LN{datetime.utcnow().strftime('%y%m')}{_suffix(6)}"


def generate_journal_entry_number() -> str:
    return f"JE{datetime.utcnow().strftime('%y%m%d')}{_suffix(5)}"
