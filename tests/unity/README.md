# Native startup and discovery checks

`StartupDiscoveryAudit.cs` is copied into disposable projects by
`scripts/verify-startup.py`; it is not part of the shipped Unity package.
The runner also extracts the baseline discovery implementation as
`LegacyToolDiscovery` for handler and schema compatibility checks.

Build a baseline single-file CLI from `main` in a separate checkout/snapshot and
the candidate bundle with the same Python/PyInstaller environment. Install or
extract the candidate archive, then run from the repository root:

```powershell
python scripts/verify-startup.py --unity-editor "C:/Program Files/Unity/Hub/Editor/6000.3.13f1/Editor/Unity.exe" --unity-version 6000.3.13f1 --baseline-bin "path/to/baseline/unity-bridge.exe" --candidate-bin "path/to/candidate/unity-bridge.exe" --output .codex-deps/startup-unity6
```

The output directory must be empty. Repeat with the installed Unity 2021 Editor
and a different output directory. Each run starts fresh Editor processes in
baseline/candidate/candidate/baseline order, observes a real matching heartbeat,
and measures the first console command without an RPC warm-up. It then checks
lazy schemas, repeated list isolation, dynamically loaded tools, duplicate names,
the baseline schema/handler contract, a real compilation/domain reload, and an
actual `exec` compilation/Assembly.Load followed by another tool-list request.
Use `--variants candidate` for a candidate-only functional follow-up.

These are empty-project batch-mode measurements, not GUI background latency or
the time from an agent prompt to its displayed answer. Previous runs are retained
and failing sessions are written before the runner exits.
