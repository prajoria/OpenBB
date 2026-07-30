"""
Mortgage Amortization Calculator
================================
Computes monthly principal & interest breakdown for a fixed-rate home mortgage.

Formula:
    M = P * [r(1+r)^n] / [(1+r)^n - 1]

Where:
    M = monthly payment (principal + interest only)
    P = loan principal
    r = monthly interest rate  (annual_rate / 12)
    n = total number of payments (years * 12)

Each month:
    interest_portion  = remaining_balance * r
    principal_portion = M - interest_portion
    remaining_balance -= principal_portion

Usage:
    calc = MortgageCalculator(loan_amount=400_000, annual_rate_pct=6.5, term_years=30)
    df   = calc.schedule()          # full amortization DataFrame
    info = calc.summary()           # dict with summary stats
    calc.print_schedule(every_n=12) # pretty-print annual view
    calc.to_csv("amort.csv")        # save to CSV
"""

from __future__ import annotations

import pandas as pd


class MortgageCalculator:
    """Fixed-rate home mortgage amortization calculator.

    All public methods return pandas DataFrames or plain dicts so the
    results are immediately usable for analysis and plotting.

    Parameters
    ----------
    loan_amount : float
        Original loan (principal) in dollars.
    annual_rate_pct : float
        Annual interest rate as a percentage (e.g. 6.5 for 6.5 %).
    term_years : int
        Loan term in years (e.g. 30).
    extra_monthly : float, optional
        Additional principal payment applied every month (default 0).
    """

    def __init__(
        self,
        loan_amount: float,
        annual_rate_pct: float,
        term_years: int,
        extra_monthly: float = 0.0,
    ) -> None:
        self.loan_amount = loan_amount
        self.annual_rate_pct = annual_rate_pct
        self.term_years = term_years
        self.extra_monthly = extra_monthly

        self._monthly_rate = annual_rate_pct / 100.0 / 12.0
        self._n_payments = term_years * 12
        self._monthly_payment = self._compute_monthly_payment()

        # Cache – built lazily on first call to schedule()
        self._schedule_df: pd.DataFrame | None = None

    # ------------------------------------------------------------------
    # Core math
    # ------------------------------------------------------------------

    def _compute_monthly_payment(self) -> float:
        """Fixed monthly P&I payment for a fully-amortizing loan."""
        r = self._monthly_rate
        n = self._n_payments
        if r == 0:
            return self.loan_amount / n
        factor = (1 + r) ** n
        return self.loan_amount * (r * factor) / (factor - 1)

    @property
    def monthly_payment(self) -> float:
        """The base monthly payment (before any extra principal)."""
        return round(self._monthly_payment, 2)

    # ------------------------------------------------------------------
    # Schedule (returns DataFrame)
    # ------------------------------------------------------------------

    def schedule(self) -> pd.DataFrame:
        """Build the full month-by-month amortization schedule.

        Returns
        -------
        pd.DataFrame
            Columns: Month, Payment, Principal, Interest,
                     Total_Interest, Balance
        """
        if self._schedule_df is not None:
            return self._schedule_df.copy()

        r = self._monthly_rate
        monthly = self._monthly_payment
        balance = self.loan_amount
        extra = self.extra_monthly

        rows: list[dict] = []
        total_interest = 0.0

        for month in range(1, self._n_payments + 1):
            interest = balance * r
            base_principal = monthly - interest
            principal_payment = base_principal + extra

            # Don't overpay
            if principal_payment > balance:
                principal_payment = balance
                payment_this_month = principal_payment + interest
            else:
                payment_this_month = monthly + extra

            balance -= principal_payment
            total_interest += interest

            rows.append(
                {
                    "Month": month,
                    "Payment": round(payment_this_month, 2),
                    "Principal": round(principal_payment, 2),
                    "Interest": round(interest, 2),
                    "Total_Interest": round(total_interest, 2),
                    "Balance": round(max(balance, 0), 2),
                }
            )

            if balance <= 0:
                break

        self._schedule_df = pd.DataFrame(rows)
        return self._schedule_df.copy()

    # ------------------------------------------------------------------
    # Summary (returns dict)
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Return a summary dict of the mortgage.

        Returns
        -------
        dict
            Keys: loan_amount, annual_rate_pct, term_years,
                  monthly_payment, total_payments, total_paid,
                  total_interest, total_principal, interest_saved
                  (if extra payments were applied).
        """
        df = self.schedule()
        total_interest = df["Interest"].sum()
        total_principal = df["Principal"].sum()
        total_paid = total_interest + total_principal

        result = {
            "loan_amount": self.loan_amount,
            "annual_rate_pct": self.annual_rate_pct,
            "term_years": self.term_years,
            "extra_monthly": self.extra_monthly,
            "monthly_payment": self.monthly_payment,
            "total_payments": len(df),
            "total_paid": round(total_paid, 2),
            "total_interest": round(total_interest, 2),
            "total_principal": round(total_principal, 2),
        }

        # If extra payments, show how many months / dollars saved
        if self.extra_monthly > 0:
            base = MortgageCalculator(
                self.loan_amount, self.annual_rate_pct, self.term_years, 0
            )
            base_df = base.schedule()
            result["months_saved"] = len(base_df) - len(df)
            result["interest_saved"] = round(
                base_df["Interest"].sum() - total_interest, 2
            )

        return result

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def print_schedule(self, every_n: int = 1) -> None:
        """Pretty-print the amortization schedule.

        Parameters
        ----------
        every_n : int
            Print every N-th row (use 12 for an annual view).
        """
        df = self.schedule()
        s = self.summary()

        print("=" * 90)
        print(f"  Loan Amount:    ${s['loan_amount']:>14,.2f}")
        print(f"  Annual Rate:    {s['annual_rate_pct']:>14.3f}%")
        print(
            f"  Term:           {s['term_years']:>14d} years  "
            f"({s['total_payments']} payments)"
        )
        print(f"  Monthly P&I:    ${s['monthly_payment']:>14,.2f}")
        if self.extra_monthly > 0:
            print(f"  Extra/month:    ${self.extra_monthly:>14,.2f}")
        print(f"  Total Paid:     ${s['total_paid']:>14,.2f}")
        print(f"  Total Interest: ${s['total_interest']:>14,.2f}")
        if "interest_saved" in s:
            print(f"  Interest Saved: ${s['interest_saved']:>14,.2f}")
            print(f"  Months Saved:   {s['months_saved']:>14d}")
        print("=" * 90)

        header = (
            f"{'Month':>6}  {'Payment':>12}  {'Principal':>12}  {'Interest':>12}  "
            f"{'Tot Interest':>14}  {'Balance':>14}"
        )
        print(header)
        print("-" * 90)

        last_month = int(df["Month"].iloc[-1])
        for _, row in df.iterrows():
            m = int(row["Month"])
            if m % every_n == 0 or m == 1 or m == last_month:
                print(
                    f"{m:>6}  ${row['Payment']:>11,.2f}  ${row['Principal']:>11,.2f}  "
                    f"${row['Interest']:>11,.2f}  ${row['Total_Interest']:>13,.2f}  "
                    f"${row['Balance']:>13,.2f}"
                )

        print("-" * 90)

    def to_csv(self, filepath: str) -> None:
        """Save the full amortization schedule to a CSV file."""
        self.schedule().to_csv(filepath, index=False)
        print(f"  Saved schedule to {filepath}")

    def __repr__(self) -> str:
        return (
            f"MortgageCalculator(loan_amount={self.loan_amount:,.2f}, "
            f"rate={self.annual_rate_pct}%, "
            f"term={self.term_years}yr, "
            f"extra={self.extra_monthly:,.2f})"
        )


# ---------------------------------------------------------------------------
# Interactive CLI
# ---------------------------------------------------------------------------

def _prompt_float(prompt: str, default: float | None = None) -> float:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            return float(raw)
        except ValueError:
            print("  Please enter a valid number.")


def _prompt_int(prompt: str, default: int | None = None) -> int:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            return int(raw)
        except ValueError:
            print("  Please enter a valid integer.")


def main() -> None:
    print("\n*** Mortgage Amortization Calculator ***\n")

    loan = _prompt_float("Loan amount ($)", 400_000)
    rate = _prompt_float("Annual interest rate (%)", 6.5)
    years = _prompt_int("Loan term (years)", 30)
    extra = _prompt_float("Extra monthly principal ($)", 0)

    calc = MortgageCalculator(loan, rate, years, extra)

    view = input("\nShow schedule every N months (1=all, 12=annual) [12]: ").strip()
    every = int(view) if view else 12

    print()
    calc.print_schedule(every_n=every)

    save = input("\nSave full schedule to CSV? (y/n) [n]: ").strip().lower()
    if save == "y":
        fname = f"amortization_{int(loan)}_{rate}pct_{years}yr.csv"
        calc.to_csv(fname)

    print()


if __name__ == "__main__":
    main()
