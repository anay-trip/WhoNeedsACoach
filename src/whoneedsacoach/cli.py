import sys

from whoneedsacoach.agent.executor import run_checkin, run_plan
from whoneedsacoach.auth.login import LoginService
from whoneedsacoach.store.repo import Repo
from whoneedsacoach.utils.config import ANAY_EMAIL, ANAY_NAME, ANAY_PASSWORD, DB_PATH, TOKEN_ROOT


def login_anay() -> None:
    """Log Anay into Garmin. A UI later calls LoginService with the form's email and password."""
    repo = Repo(DB_PATH)
    service = LoginService(repo, TOKEN_ROOT)
    result = service.begin(ANAY_NAME, ANAY_EMAIL, ANAY_PASSWORD)
    if result.get("status") == "mfa_required":
        code = input("Enter the Garmin MFA code: ")
        result = service.submit_mfa(result["attempt_id"], code)
    if result.get("error"):
        print(result["error"])
        return
    print(f"Garmin tokens saved for {ANAY_NAME} at {result['garmin_token_dir']}")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if command == "login":
        login_anay()
        return
    if command == "checkin":
        run_checkin()
        return
    run_plan()


if __name__ == "__main__":
    main()
