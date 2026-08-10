# Security Policy

## Scope

This policy covers the Agent Memory Protocol (AMP) project, including:

- The protocol specification (`spec/v0.1.0/`), including its security model
  (access control policy, agent identity headers, and related normative
  requirements described in the spec documents)
- The reference server implementation (`server/`)
- The reference SDK / client implementation (`sdk/`)

If you are unsure whether an issue falls within scope, please report it
anyway and we will help route or close it out.

## Supported Versions

AMP is pre-1.0 and does not yet maintain multiple parallel release branches.
Security reports are evaluated against the latest spec version
(`spec/v0.1.0/`) and the latest code on the default branch.

## Reporting a Vulnerability

Please report suspected security vulnerabilities using **GitHub Security
Advisories** for this repository:

1. Go to the repository's **Security** tab.
2. Select **Report a vulnerability** to open a new private security advisory.
3. Include as much detail as possible: affected component (spec, server, or
   SDK), the version or commit affected, steps to reproduce, and potential
   impact.

Do not report security vulnerabilities through public GitHub issues, pull
requests, or discussions, since these are publicly visible.

## What to Include

To help us triage and resolve issues efficiently, please include where
applicable:

- A clear description of the vulnerability and its impact
- The affected file(s), spec section, or endpoint
- Steps to reproduce, or a minimal proof of concept
- Any known mitigations or workarounds

## Response Process

- **Acknowledgement:** We will acknowledge receipt of your report within
  **72 hours**.
- **Triage:** We will assess the report, confirm whether it constitutes a
  vulnerability, and determine its severity and scope (spec, server, and/or
  SDK).
- **Resolution:** For confirmed vulnerabilities, we aim to resolve and
  disclose within **90 days** of the initial report. This may take the form
  of a code fix, a spec amendment, or documented mitigation guidance,
  depending on where the issue originates.
- **Disclosure:** We will coordinate disclosure timing with the reporter.
  Once a fix or mitigation is available, we will publish an advisory
  through the repository's Security tab crediting the reporter, unless
  anonymity is requested.

## Spec vs. Implementation Issues

Because AMP is both a specification and a reference implementation:

- Issues in the **reference server or SDK code** (e.g., improper enforcement
  of access control, injection vulnerabilities, insecure defaults) will be
  addressed with a code patch.
- Issues in the **protocol specification itself** (e.g., a security model
  gap that would affect any correct implementation) will be addressed with
  a spec amendment or clarification, referencing the relevant section of
  `spec/v0.1.0/`.

Reports that affect both will be tracked and resolved on both tracks.
