"""Merges two .json files."""
import json
import json5
import sys


def main(args):
    infile_path=args[0]
    outfile_path=args[1]
    print(f"Merging JSON from '{infile_path}' into '{outfile_path}'")

    with open(infile_path, encoding="utf-8") as infile:
        new_data=json5.load(infile)

    with open(outfile_path, encoding="utf-8") as infile:
        old_data=json5.load(infile)

    old_data.update(new_data)

    with open(outfile_path, "w", encoding="utf-8") as outfile:
        json.dump(old_data, outfile)
        
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
