"""Patch the inspected LeRobot recorder to save Lumos's actual limited target.

Only changes recording for robot.name == 'lumos'; creates a backup first.
No motion or hardware connection is performed by this script.
"""

import argparse
import ast
from pathlib import Path

MARKER = "# lumos: store the action returned by send_action"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="LeRobot src/lerobot/scripts/lerobot_record.py")
    args = parser.parse_args()
    source = args.path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Already patched")
        return
    old = "action_frame = build_dataset_frame(dataset.features, action_values, prefix=ACTION)"
    guard = "    if dataset is not None and dataset.fps != fps:"
    if source.count(old) != 1 or source.count(guard) != 1:
        raise SystemExit("Recorder differs from inspected version; no file changed. Review manually.")
    if "_sent_action = robot.send_action(robot_action_to_send)" not in source:
        raise SystemExit("Expected send_action assignment missing; no file changed")
    updated = source.replace(
        old,
        (
            f"{MARKER}\n"
            "                recorded_action = _sent_action if robot.name == 'lumos' else action_values\n"
            "                action_frame = build_dataset_frame(dataset.features, recorded_action, prefix=ACTION)"
        ),
    )
    updated = updated.replace(
        guard,
        (
            "    if dataset is not None and robot.name == 'lumos' and not robot.config.execute:\n"
            "        raise ValueError('Lumos recording requires execute=true; use teleoperate for preview')\n\n"
            + guard
        ),
    )
    ast.parse(updated)
    backup = args.path.with_name(args.path.name + ".before_lumos.bak")
    with backup.open("x", encoding="utf-8") as stream:
        stream.write(source)
    args.path.write_text(updated, encoding="utf-8")
    print(f"Patched {args.path}; backup: {backup}")


if __name__ == "__main__":
    main()
