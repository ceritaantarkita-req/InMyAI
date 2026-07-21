# Security

## Threat model summary

The highest-risk capability is local filesystem and terminal access, not chat generation.

## Current controls

- explicit project registration
- allowed-root policy
- path canonicalization and traversal prevention
- common system/credential paths blocked
- common secret filenames blocked
- direct file size limit
- write proposal and unified diff
- explicit Apply or Reject
- timestamped backup before overwrite
- audit log
- no API keys stored by the current P0 UI
- local-only default endpoints

## Not yet implemented

- OS-native capability sandbox
- code signing
- encrypted database
- multi-user authentication
- terminal execution tool
- Tauri permission scopes

These must be completed before positioning InMyAI as a secure multi-user or enterprise application.

## Public repository rules

Never commit:

- `.env`
- model weights
- SQLite runtime databases
- indexed private projects
- OCR output from sensitive files
- Graphify output from private folders
- generated private artifacts
