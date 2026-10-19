"""Export an explicitly selected model's URDF limits. Review before real execution."""

import argparse
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--joint-names", default="joint1,joint2,joint3,joint4,joint5,joint6")
    args = parser.parse_args()
    names = args.joint_names.split(",")
    if len(names) != 6 or len(set(names)) != 6:
        parser.error("Provide six distinct URDF joint names in SDK order")
    joints = {j.attrib["name"]: j for j in ET.parse(args.urdf).getroot().findall("joint")}
    lower, upper = [], []
    for name in names:
        joint = joints[name]
        if joint.attrib.get("type") != "revolute":
            raise ValueError(f"{name} is not a bounded revolute joint")
        limit = joint.find("limit")
        lo, hi = float(limit.attrib["lower"]), float(limit.attrib["upper"])
        if not math.isfinite(lo) or not math.isfinite(hi) or lo >= hi:
            raise ValueError(f"Invalid bounds for {name}")
        lower.append(lo)
        upper.append(hi)
    data = {
        "lower_rad": lower,
        "upper_rad": upper,
        "source_urdf": str(args.urdf.resolve()),
        "joint_names": names,
    }
    # Never overwrite an existing reviewed configuration silently.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
    print(json.dumps(data, indent=2))
    print("Review joint order, SDK coordinates and installed robot model before use.")


if __name__ == "__main__":
    main()
