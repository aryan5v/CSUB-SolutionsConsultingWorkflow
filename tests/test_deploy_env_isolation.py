from __future__ import annotations

import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy.yml"

VITE_VARS = (
    "VITE_API_BASE_URL",
    "VITE_COGNITO_DOMAIN",
    "VITE_COGNITO_CLIENT_ID",
    "VITE_COGNITO_REDIRECT_URI",
    "VITE_COGNITO_LOGOUT_URI",
)


def _lines() -> list[str]:
    return WORKFLOW.read_text(encoding="utf-8").splitlines()


def _section(start_marker: str, end_markers: tuple[str, ...]) -> list[str]:
    """Return the lines from the first line containing start_marker up to (not
    including) the next line containing any end marker. Used to isolate a single
    workflow step or the job-level env block without a YAML dependency."""
    lines = _lines()
    for index, line in enumerate(lines):
        if start_marker in line:
            body: list[str] = []
            for follow in lines[index + 1 :]:
                if any(marker in follow for marker in end_markers):
                    break
                body.append(follow)
            return body
    raise AssertionError(f"marker not found in deploy workflow: {start_marker!r}")


class DeployEnvIsolationTests(unittest.TestCase):
    """Regression guard for issue #60: live deployment configuration must never
    leak into the hermetic `make verify` step of the deploy workflow."""

    def test_job_level_env_has_no_vite_values(self) -> None:
        job_env = _section("    env:", ("    steps:",))
        for var in VITE_VARS:
            self.assertNotIn(
                var,
                "\n".join(job_env),
                f"{var} must not be defined at job scope; it leaks into make verify",
            )

    def test_verify_step_receives_no_vite_values(self) -> None:
        verify_step = _section(
            "Verify repository without cloud credentials", ("- name:",)
        )
        self.assertNotIn("env:", "\n".join(verify_step))
        for var in VITE_VARS:
            self.assertNotIn(var, "\n".join(verify_step))

    def test_hermetic_guard_runs_before_verify(self) -> None:
        lines = _lines()
        guard = next(
            i for i, l in enumerate(lines) if "Assert hermetic verification environment" in l
        )
        verify = next(
            i for i, l in enumerate(lines) if "Verify repository without cloud credentials" in l
        )
        self.assertLess(guard, verify, "hermetic guard must precede make verify")
        for var in VITE_VARS:
            self.assertIn(var, "\n".join(lines[guard:verify]))

    def test_frontend_build_step_receives_live_values(self) -> None:
        build_step = _section(
            "Build live frontend without cloud credentials", ("- name:",)
        )
        for var in VITE_VARS:
            self.assertIn(
                var,
                "\n".join(build_step),
                f"{var} must be scoped to the production frontend build step",
            )


if __name__ == "__main__":
    unittest.main()
