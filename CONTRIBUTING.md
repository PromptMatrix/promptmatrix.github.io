# Contributing to PromptMatrix

Thank you for your interest in contributing! PromptMatrix is an open-source, local-first prompt governance engine. All contributions — bug reports, documentation improvements, feature requests, and code — are welcome.

---

## 🗺️ Project Philosophy

PromptMatrix is designed to stay **fiercely local-first**. The core principle:

> No external accounts, no cloud, no dependencies beyond standard Python and SQLite. Anyone should be able to clone and run in under 60 seconds.

When contributing, keep this constraint in mind. Features that introduce mandatory external services belong in a separate fork or cloud layer.

---

## 🐛 Reporting Bugs

1. Check [existing issues](https://github.com/PromptMatrix/promptmatrix.github.io/issues) first.
2. Open a new issue with:
   - OS and Python version
   - Steps to reproduce
   - Expected vs. actual behavior
   - Relevant logs or error messages

---

## 🚀 Submitting a Pull Request

1. **Fork** the repository and create a branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```

2. **Set up your environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env
   alembic upgrade head
   ```

3. **Make your changes** — keep PRs focused and atomic.

4. **Run the test suite:**
   ```bash
   pytest
   ```
   All tests must pass before submitting.

5. **Add tests** for any new functionality.

6. **Write a clear PR description** explaining what changed and why.

---

## 🧪 Testing

Tests live in `tests/`. Run with:
```bash
pytest
```

The test suite uses an in-memory SQLite database and does not require any external services.

---

## 📄 License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
