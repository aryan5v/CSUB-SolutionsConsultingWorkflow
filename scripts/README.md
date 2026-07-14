# Scripts

Put repeatable local development, validation, and AWS CLI helpers here. Scripts should fail clearly, accept configuration through environment variables or arguments, and avoid printing secrets.

## Repository validation

Run the dependency-free repository, documentation-link, secret-pattern, syntax, and unit checks locally with:

```bash
make verify
```

GitHub Actions runs the same aggregate command for every pull request into `main` and every push to `main`. `scan_secrets.py` is intentionally a fast local backstop; GitHub secret scanning and push protection remain authoritative.
