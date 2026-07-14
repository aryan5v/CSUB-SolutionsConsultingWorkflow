# Scripts

Put repeatable local development, validation, and AWS CLI helpers here. Scripts should fail clearly, accept configuration through environment variables or arguments, and avoid printing secrets.

## Repository validation

Run the dependency-free repository, documentation-link, and plan-coverage checks locally with:

```bash
make check
```

GitHub Actions runs the same command for every pull request into `main` and every push to `main`.
