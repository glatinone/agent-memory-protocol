# Contributing to AMP

Thank you for your interest in contributing to AMP! This guide will help you get set up and walk you through our development processes.

---

## Table of Contents
1. [Setting Up Your Development Environment](#setting-up-your-development-environment)
2. [Running Tests](#running-tests)
3. [Pull Request Process](#pull-request-process)
4. [Code Style & Standards](#code-style--standards)
5. [RFC Process (Protocol Spec Changes)](#rfc-process-protocol-spec-changes)

---

## Setting Up Your Development Environment

To start developing, ensure you have Python 3.10+ installed. Then, clone the repository and install the package in editable mode along with development dependencies:

```bash
# Clone the repository
git clone https://github.com/your-username/amp.git
cd amp

# Create and activate a virtual environment (optional but recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the package and dev dependencies
pip install -e ".[dev]"
```

---

## Running Tests

We use `pytest` for running our test suite. Make sure your changes do not break any existing tests and that you write tests for any new features or bug fixes.

To run the entire test suite:
```bash
pytest tests/
```

To run a specific test file:
```bash
pytest tests/test_example.py
```

To run tests with coverage reporting:
```bash
pytest --cov=amp tests/
```

---

## Pull Request Process

We follow a typical Git branch workflow for all changes:

1. **Create a Branch:** Create a descriptively named branch from the main branch.
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b bugfix/issue-id-description
   ```
2. **Implement Changes:** Write your code, adding documentation and tests as needed.
3. **Verify Locally:** Run the tests using `pytest` and check code formatting/style.
4. **Push & Create PR:** Push your branch to GitHub and open a Pull Request.
5. **Link Issues:** In your PR description, link any related issues (e.g., `Closes #123` or `Fixes #456`).
6. **Review & Iterate:** Wait for review from the project maintainers and address any feedback.

---

## Code Style & Standards

To keep the codebase clean, consistent, and maintainable, we adhere to the following:

- **PEP 8:** We follow PEP 8 styling conventions.
- **Formatter (Black):** We use `black` for auto-formatting code. You can format code with:
  ```bash
  black amp/ tests/
  ```
- **Type Hints:** We encourage and require type hints for all new functions, methods, and classes to ensure type safety and aid editor completion.

---

## RFC Process (Protocol Spec Changes)

If you wish to propose a protocol specification change or addition, you must submit an RFC (Request for Comments) first:

1. Create a markdown file describing your proposed specification changes under `spec/rfcs/` (e.g., `spec/rfcs/0001-my-proposal.md`).
2. Open a Pull Request referencing the RFC.
3. Once the RFC is reviewed, discussed, and merged, you can proceed with the corresponding implementation.
