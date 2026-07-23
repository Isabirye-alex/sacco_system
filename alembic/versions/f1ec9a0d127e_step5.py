"""step5

Revision ID: f1ec9a0d127e
Revises: 8f1022f475a3
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1ec9a0d127e'
down_revision: Union[str, None] = '8f1022f475a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'referrals',
        sa.Column('referral_code', sa.String(length=16), nullable=False),
        sa.Column('referrer_member_id', sa.String(length=36), nullable=False),
        sa.Column('referred_name', sa.String(length=150), nullable=False),
        sa.Column('referred_contact', sa.String(length=150), nullable=False),
        sa.Column('channel', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('invited_at', sa.DateTime(), nullable=False),
        sa.Column('registered_member_id', sa.String(length=36), nullable=True),
        sa.Column('registered_at', sa.DateTime(), nullable=True),
        sa.Column('commission_amount', sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column('commission_paid_savings_account_id', sa.String(length=36), nullable=True),
        sa.Column('commission_paid_at', sa.DateTime(), nullable=True),
        sa.Column('commission_paid_by_user_id', sa.String(length=36), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['commission_paid_by_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['commission_paid_savings_account_id'], ['savings_accounts.id']),
        sa.ForeignKeyConstraint(['referrer_member_id'], ['members.id']),
        sa.ForeignKeyConstraint(['registered_member_id'], ['members.id']),
        sa.PrimaryKeyConstraint('id'),
        if_not_exists=True,
    )
    op.create_index(
        op.f('ix_referrals_referral_code'),
        'referrals',
        ['referral_code'],
        unique=True,
        if_not_exists=True,
    )

    op.create_table(
        'payslips',
        sa.Column('payroll_run_id', sa.String(length=36), nullable=False),
        sa.Column('employee_id', sa.String(length=36), nullable=False),
        sa.Column('basic_salary', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('allowances', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('gross_pay', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('paye_amount', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('nssf_employee_amount', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('nssf_employer_amount', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('loan_deduction_amount', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('loan_id', sa.String(length=36), nullable=True),
        sa.Column('net_pay', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('payment_status', sa.String(length=20), nullable=False),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('paid_by_user_id', sa.String(length=36), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id']),
        sa.ForeignKeyConstraint(['loan_id'], ['loan_applications.id']),
        sa.ForeignKeyConstraint(['paid_by_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['payroll_run_id'], ['payroll_runs.id']),
        sa.PrimaryKeyConstraint('id'),
        if_not_exists=True,
    )

    op.add_column(
        'savings_accounts',
        sa.Column('last_interest_posted_at', sa.DateTime(), nullable=True),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_referrals_referral_code'), table_name='referrals', if_exists=True)
    op.drop_table('referrals', if_exists=True)
    op.drop_table('payslips', if_exists=True)
