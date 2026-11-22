from summarize.summarizer import project_label


def test_project_label_takes_folder_after_last_anchor():
    cases = {
        "-Users-tongtongtot-Desktop-algorithms-CEI-robot-arms": "CEI-robot-arms",
        "C--Users-tongt-Documents-GitHub-gadget": "gadget",
        "-run-media-thomas-Windows-Users-tongt-Documents-GitHub-gadget": "gadget",
        "C--Users-tongt-Documents-GitHub-gadget-website": "gadget",
        "C--Users-tongt-Documents-GitHub-TokenMonitor-src-tauri-target-release": "TokenMonitor",
        "C--Users-tongt-AppData-Local-TokenMonitor": "TokenMonitor",
        "-hpc-group-yizhanglab-zt81-MIHD": "MIHD",
        "-XYFS01-HDD-POOL-sysu-gbli2-sysu-gbli2xy-1-tangzijia-error-recovery-benchmark": "error-recovery-benchmark",
        "D--Github-LiveCaption": "LiveCaption",
        "ErrorRecoveryBenchmark": "ErrorRecoveryBenchmark",  # codex: bare folder
    }
    for raw, want in cases.items():
        assert project_label(raw) == want, raw


def test_project_label_none_for_pathless_sessions():
    for raw in ["-", "", None, "D--Github", "C--Users-tongt", "C--Windows-system32", "D:\\",
                "ssh-f8a0b860-312c-433e-a84f-722dde495a00", "empty-window",
                "-Users-x-Library-Application-Support-Claude-scratch-workspaces-abc"]:
        assert project_label(raw) == "(none)", raw
