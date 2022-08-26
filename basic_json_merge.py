"""Merges two .json files."""
import json
import json5
import sys

def merge_dicts(a: dict, b: dict, path=None):
    """Merges b into a, replacing any non-container values."""
    if path is None:
        path = []
        
    for key, b_value in b.items():
        if key not in a:
            a[key] = b_value
            continue

        a_value = a[key]
        if isinstance(a_value, dict):
            if not isinstance(b_value, dict):
                raise ValueError(f"a[{key}] is a dict, but b[{key}] is not!")
            merge_dicts(a_value, b_value, path + [str(key)])
            continue

        if isinstance(a_value, list):
            if not isinstance(b_value, list):
                raise ValueError(f"a[{key}] is a list, but b[{key}] is not!")

            a_value.extend(b_value)
            continue

        a[key] = b_value

    return a


def main(args):
    infile_path=args[0]
    outfile_path=args[1]
    print(f"Merging JSON from '{infile_path}' into '{outfile_path}'")

    with open(infile_path, encoding="utf-8") as infile:
        new_data=json5.load(infile)

    with open(outfile_path, encoding="utf-8") as infile:
        old_data=json5.load(infile)

    merge_dicts(old_data, new_data)

    with open(outfile_path, "w", encoding="utf-8") as outfile:
        json.dump(old_data, outfile)
        
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
