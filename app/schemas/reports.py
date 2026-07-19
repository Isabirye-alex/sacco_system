from pydantic import BaseModel


class AccountLine(BaseModel):
    code: str
    name: str
    balance: str


class BalanceSheetResponse(BaseModel):
    as_of: str
    assets: list[dict]
    liabilities: list[dict]
    equity: list[dict]
    total_assets: str
    total_liabilities: str
    total_equity: str
    balances: bool


class IncomeStatementResponse(BaseModel):
    period: dict
    income: list[dict]
    expenses: list[dict]
    total_income: str
    total_expenses: str
    net_surplus: str
