from datetime import datetime
from sqlalchemy.orm import Session
from app.models.savings import SavingsAccount
from app.models.loan import LoanApplication

def generate_savings_statement_html(db: Session, account_id: str) -> str:
    account = db.get(SavingsAccount, account_id)
    if not account:
        return "<h1>Account Not Found</h1>"

    txns_html = ""
    for t in account.transactions:
        txns_html += f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #eee;">{t.created_at.strftime('%Y-%m-%d %H:%M')}</td>
            <td style="padding: 10px; border-bottom: 1px solid #eee;">{t.txn_type.value}</td>
            <td style="padding: 10px; border-bottom: 1px solid #eee;">{t.narrative or '-'}</td>
            <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: right;">{t.amount:,.2f}</td>
            <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: right;"><strong>{t.balance_after:,.2f}</strong></td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>SACCO Savings Statement - {account.account_number}</title>
        <style>
            body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #1a1a1a; padding: 40px; }}
            .header {{ display: flex; justify-content: space-between; border-bottom: 2px solid #10b981; padding-bottom: 20px; margin-bottom: 30px; }}
            .title {{ font-size: 24px; font-weight: bold; color: #065f46; }}
            .info-table {{ width: 100%; margin-bottom: 30px; border-collapse: collapse; }}
            .info-table td {{ padding: 6px; font-size: 14px; }}
            .ledger-table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            .ledger-table th {{ background: #065f46; color: white; padding: 12px 10px; text-align: left; font-size: 13px; }}
            .stamp {{ display: inline-block; padding: 8px 16px; border: 2px dashed #10b981; color: #10b981; font-weight: bold; margin-top: 30px; border-radius: 6px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div>
                <div class="title">SACCO COOPERATIVE SOCIETY</div>
                <div style="color: #666; font-size: 12px;">Official Member Account Statement</div>
            </div>
            <div style="text-align: right; font-size: 12px; color: #666;">
                Generated: {datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')}<br>
                Statement Ref: STMT-{account.account_number}
            </div>
        </div>

        <table class="info-table">
            <tr>
                <td><strong>Member Name:</strong> {account.member.full_name}</td>
                <td><strong>Account Number:</strong> {account.account_number}</td>
            </tr>
            <tr>
                <td><strong>Member Number:</strong> {account.member.member_number}</td>
                <td><strong>Account Product:</strong> {account.product.name}</td>
            </tr>
            <tr>
                <td><strong>Current Balance:</strong> UGX {account.balance:,.2f}</td>
                <td><strong>Account Status:</strong> {'ACTIVE' if account.is_active else 'INACTIVE'}</td>
            </tr>
        </table>

        <h3>Transaction History</h3>
        <table class="ledger-table">
            <thead>
                <tr>
                    <th>Date & Time</th>
                    <th>Type</th>
                    <th>Description</th>
                    <th style="text-align: right;">Amount (UGX)</th>
                    <th style="text-align: right;">Balance After</th>
                </tr>
            </thead>
            <tbody>
                {txns_html if txns_html else '<tr><td colspan="5" style="text-align: center; padding: 20px; color: #888;">No transactions found.</td></tr>'}
            </tbody>
        </table>

        <div class="stamp">OFFICIALLY VERIFIED • SACCO LEDGER SYSTEM</div>
    </body>
    </html>
    """
