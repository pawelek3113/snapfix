from snapfix import MemoriesFixer
from pathlib import Path
from snapfix import LoggerBuilder
import argparse
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(prog="snapfix", description="A script that fixes datetime metadata tags for snapchat memories and composes main and overlay into a single item.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fix_parser = subparsers.add_parser("fix-dates")
    fix_parser.add_argument("root_dir", type=Path, help="Root directory that holds memories with their dates to be fixed (they can be nested).")
    fix_parser.add_argument("-d", "--dry-run", action="store_true", help="Runs the program without affecting your files.")

    compose_parser = subparsers.add_parser("compose")
    compose_parser.add_argument("root_dir", type=Path, help="Root directory that holds memories (main and overlay files) (they can be nested).")
    compose_parser.add_argument("output_dir", type=Path, help="Directory that will hold composited items.")
    compose_parser.add_argument("--dry-run", action="store_true", help="Runs the program without affecting your files.")

    args = parser.parse_args()

    lg = LoggerBuilder().build(Path(f"memories_fix_{datetime.now().strftime("%Y_%m_%d_%H-%M-%S")}.log"))

    if args.command == "fix-dates":
        with MemoriesFixer(root_dir=args.root_dir, dry_run=args.dry_run, logger=lg) as fixer:
            fixer.fix_dates()
    elif args.command == "compose":
        with MemoriesFixer(root_dir=args.root_dir, dry_run=args.dry_run, logger=lg) as fixer:
            # fixer.compose_all(args.output_dir)
            lg.warning("compose command is not implemented yet")
            ...


if __name__ == "__main__":
    main()